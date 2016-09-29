import time

import numpy as np
from scipy.fftpack import dst, idst


import pyoz as oz
from pyoz.closure import supported_closures
from pyoz.exceptions import PyozError
from pyoz.misc import rms_normed, solver, picard_iteration


def _get_closure_func(closure_name, **kwargs):
    if closure_name.upper() == 'RHNC':
        if kwargs.get('g_r_ref') is None:
            raise PyozError('Missing `g_r_ref` parameter for RHNC closure.')
        if kwargs.get('e_r_ref') is None:
            raise PyozError('Missing `e_r_ref` parameter for RHNC closure.')
        if kwargs.get('U_r_ref') is None:
            raise PyozError('Missing `U_r_ref` parameter for RHNC closure.')
    try:
        closure = supported_closures[closure_name.upper()]
    except KeyError:
        raise PyozError('Unsupported closure: ', closure_name)

    return closure


class System(object):
    def __init__(self, name='System', **kwargs):
        self.name = name
        self.T = kwargs.get('T') or 1

        # Algorithm control
        # =================
        n_points_exp = kwargs.get('n_points_exp') or 12
        self.n_points = kwargs.get('n_points') or 2**n_points_exp
        self.n_points -= 1

        self.dr = kwargs.get('dr') or 0.01

        max_r = self.dr * self.n_points
        self.dk = np.pi / max_r

        # System info
        # ===========
        # TODO: units
        dr = self.dr
        dk = self.dk
        self.r = np.linspace(dr, self.n_points * dr - dr, self.n_points)
        self.k = np.linspace(dk, self.n_points * dk - dk, self.n_points)
        self.U_r = np.zeros(shape=(0, 0, self.n_points))
        self.rho = None

        # Results get stored after `System.solve` successfully completes.
        self.g_r = self.h_r = self.c_r = self.e_r = self.S_k = None

    @property
    def n_components(self):
        return self.U_r.shape[0]

    def set_interaction(self, comp1_idx, comp2_idx, potential, symmetric=True):
        if len(potential) != self.n_points:
            raise PyozError('Attempted to add values at {} points to potential'
                            'with {} points.'.format(potential.shape, self.n_points))
        if comp1_idx >= self.n_components or comp2_idx >= self.n_components:
            n_bigger = max(comp1_idx, comp2_idx) - self.U_r.shape[0] + 1
            self.U_r.resize((self.U_r.shape[0] + n_bigger,
                             self.U_r.shape[1] + n_bigger,
                             self.n_points))
        self.U_r[comp1_idx, comp2_idx] = potential
        if symmetric and comp1_idx != comp2_idx:
            self.U_r[comp2_idx, comp1_idx] = potential

        if symmetric and comp1_idx != comp2_idx:
            self.U_r[comp2_idx, comp1_idx] = potential

    def remove_interaction(self, comp1_idx, comp2_idx):
        # Needs to reduce size of U_r if comp1_idx == comp2_idx
        raise NotImplementedError

    def solve(self, rhos, closure_name='hnc', initial_e_r=None, mix_param=0.8,
              tol=1e-9, status_updates=False,  max_iter=1000, **kwargs):
        rhos = self._validate_solve_inputs(rhos)
        closure = _get_closure_func(closure_name, **kwargs)
        self._set_rhos(rhos)

        U_r = self.U_r
        n_components = self.n_components
        n_points = self.n_points

        if initial_e_r is None:
            e_r = np.zeros_like(U_r)
        else:
            e_r = initial_e_r

        matrix_shape = (n_components, n_components, n_points)
        C_k = np.zeros(matrix_shape)
        E = np.zeros(matrix_shape)
        for n in range(n_points):
            E[:, :, n] = np.eye(n_components)

        n_iter = 0
        logger = oz.logger
        if status_updates:
            logger.info('Initialized: {}'.format(self))
            logger.info('Starting iteration...')
            logger.info('   {:8s}{:10s}{:10s}'.format(
                'step', 'time (s)', 'error'))
        start = time.time()
        while n_iter < max_iter:
            loop_start = time.time()
            n_iter += 1
            e_r_previous = np.copy(e_r)

            # Apply the closure relation.
            c_r = closure(U_r, e_r, self.T, **kwargs)

            # Take us to fourier space.
            for i, j in np.ndindex(n_components, n_components):
                constant = 2 * np.pi * self.rho[i, j] * self.dr / self.k
                transform = dst(c_r[i, j] * self.r, type=1)
                C_k[i, j] = constant * transform

            # Solve dat equation.
            A = E - C_k
            B = C_k
            H_k = solver(A, B)
            S_k = 1 + H_k
            E_k = H_k - C_k

            # Snap back to reality.
            for i, j in np.ndindex(n_components, n_components):
                constant = n_points * self.dk / 4 / np.pi**2 / (n_points + 1) / self.r / self.rho[i, j]
                transform = idst(E_k[i, j] * self.k, type=1)
                e_r[i, j] = constant * transform

            # Test for convergence.
            rms_norm = rms_normed(e_r, e_r_previous)
            if rms_norm < tol:
                break

            if np.isnan(rms_norm) or np.isinf(rms_norm):
                raise PyozError('Diverged at iteration # {}'.format(n_iter))

            # Iterate.
            e_r = picard_iteration(e_r, e_r_previous, mix_param)

            if status_updates:
                logger.info('   {:<8d}{:<8.2f}{:<8.2e}'.format(
                    n_iter, time.time() - loop_start, rms_norm)
                )
        else:
            raise PyozError('Exceeded max # of iterations: {}'.format(n_iter))
        end = time.time()

        # Set before S_k error so you can still extract info if unphysical.
        c_r = closure(U_r, e_r, self.T, **kwargs)
        self.c_r = c_r
        self.g_r = g_r = c_r + e_r + 1
        self.h_r = g_r - 1
        self.e_r = e_r
        self.S_k = S_k

        if (S_k < 0).any():
            raise PyozError('Converged to unphysical result.')

        logger.info('Converged in {:.2f}s after {} iterations'.format(
            end-start, n_iter)
        )
        return g_r, c_r, e_r, S_k

    def _validate_solve_inputs(self, rhos):
        if self.U_r.shape[0] == 0:
            raise PyozError('No interactions to solve. Use `add_interaction`'
                            'before calling `solve`.')
        if not hasattr(rhos, '__iter__'):
            rhos = [rhos]
        if self.U_r.shape[0] != len(rhos):
            raise PyozError("Number of ρ's provided does not match dimensions"
                            " of potential")
        return rhos

    def _set_rhos(self, rhos):
        self.rho = np.zeros(shape=(self.n_components, self.n_components))
        for i, j in np.ndindex(self.rho.shape):
            rho_ij = np.sqrt(rhos[i] * rhos[j])
            self.rho[i, j] = rho_ij

    def __repr__(self):
        descr = list('<{}'.format(self.name))
        if self.rho is not None:
            descr.append('; {} component'.format(self.rho.shape[0]))
            if self.rho.shape[0] > 1:
                descr.append('s')
            descr.append('; ρ:')
            for rho in self.rho.diagonal():
                descr.append(' {:.6g}'.format(rho))
        descr.append('>')
        return ''.join(descr)
