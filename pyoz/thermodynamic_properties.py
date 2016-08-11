import numpy as np
from scipy import integrate


def compute_kirkwood_buff(r, g_r):
    """Compute the Kirkwood-Buff integrals.

    G_ij = 4 pi \int_0^\inf [g_ij(r)-1]r^2 dr
    """
    return 4.0 * np.pi * integrate.simps(y=(g_r - 1.0) * r**2,
                                         x=r,
                                         even='last')


def osmotic_coeff(ctrl, syst, parm, const, r, g_r_ij, G_r_ij, G_term_ij,
                  U_ij_individual, dU_ij_individual, U_discontinuity,
                  modMayerFuncContrib):
    """
       calculates the osmotic coefficient in real space

       more information can be found below
    """
    osm_coeff = 1.0

    if (syst['dens']['totnum'] == 0.0):
        # infinite dilution
        prefactor = 0.0
    else:
        # calculate the prefactor 4 pi / 6 rho
        prefactor = 2.0 * np.pi / (3.0 * syst['dens']['totnum'])
    # end if (syst['dens']['totnum'] == 0.0)

    # calculate separately the contributions of individual potentials
    oc_contrib = []

    # the expression for the osmotic coefficient is
    # phi = 1 - 1/(6 rho kT) \sum_i \sum_j [ rho_i rho_j \int_0^\infty dU/dr g_ij 4 pi r^3 dr]
    # where U is the total pair potential at infinite dilution
    # it can be dissected into individual contributions that are treated separately
    # phi = 1 + \sum_i \sum_j rho_i rho_j (2 pi)/(3 rho) * \int_0^\infty A dr
    # for U = sum_i U_i, the expression we need to evaluate is (skipping the indices)
    # A = -1/kT dU/dr g_ij r^3 dr = -1/kT \sum_i \int_0^\infty dU_i/dr g r^3
    # then
    # A = \sum_i r^3 dr d(-U_i/kT)/dr exp(-U_i/kT) Gamma_term \prod_(j not i) exp(-U_j/kT)
    # since g = exp(\sum_i -U_i/kT) Gamma_term, i.e., we are separating the contribution of a given
    # potential type and the other potentials
    # it follows then
    # A = \sum_i r^3 dr d(exp(-U_i/kT))/dr Gamma_term \prod_(j not i) exp(-U_j/kT)
    # the other possibility is to evaluate (numerically or analytically) the derivative of the interaction potential
    # and write
    # A = \sum_i -r^3/kT dU_i/dr g dr

    for pot_index in range(len(parm)):
        potential = parm[pot_index]
        oc_contrib.append(0.0)

        # ****************************************

        # hard spheres potential
        # for hard spheres, the dU/dr = delta function -> the osmotic coefficient is
        # dependent only on the value of the HS radii
        if (potential['pot_type'] == 'hs'):
            # in this case it's better to use the first expression, involving dg/dr,
            # due to discontinuity in the potential. since the g_{hs}(r) is the Heaviside
            # step function, d(g_{hs})/dr is the Dirac delta function located at sigma (contact distance)
            # the expression for A can be then simplified to
            # A_{hs} = r^3 delta(sigma - r) exp(Gamma) \prod_(j not i) exp(-U_j/kT)
            # and the resulting integral can be solved analytically for the hard spheres contribution
            # \int_0^\infty A dr = sigma^3 exp(Gamma(sigma) \prod_(j not i) exp(-U_j(sigma)/kT)

            for i in range(syst['ncomponents']):
                for j in range(syst['ncomponents']):
                    # where is the discontinuity? get the index of the array from U_discontinuity
                    # it is standard N-dimensional list => indexes have to be given separately
                    dr, left_neigh, right_neigh = U_discontinuity[pot_index][i][
                        j]
                    sigma = (dr + 1) * ctrl['deltar']

                    # evaluate the expression without the product of other potential contributions
                    val = prefactor * syst['dens']['num'][i] * \
                          syst['dens']['num'][j] * G_term_ij[
                              i, j, dr] * sigma ** 3
                    # now multiply with other potential contributions
                    for pot_index_exc in range(len(parm)):
                        if (pot_index_exc != pot_index):
                            val *= modMayerFuncContrib[pot_index_exc][i, j, dr]
                            # print("contribution", pot_index_exc, i, j, dr)
                    # and add the result to the contribution of this potential
                    oc_contrib[-1] += val
                    # end for j in range(ctrl['ncomponents'])
                    # end for i in range(ctrl['ncomponents'])
        # end if (potential['pot_type'] == 'hs')

        # ****************************************

        elif (potential['pot_type'] == 'coulomb'):
            # since the analytic expression for dU_{coul}/dr is known, it's better to use
            # it directly in the evaluation - it's -U(coul)/r
            # dU_{coul}/dr = - bjerrum_length * qi * qj / r^2 = -U(coul)/r
            # the expression for A
            # A = -1/kT dU/dr g r^3 dr
            # can be then simplified to (interaction energy is in kT units, so the
            # prefactor 1/kT cancels out) and
            # A_{coul} = U(coul) * g * r^2 dr
            # the resulting integral is then evaluated numerically

            for i in range(syst['ncomponents']):
                for j in range(syst['ncomponents']):
                    integrand = U_ij_individual[pot_index][i, j] * g_r_ij[
                        i, j] * r ** 2

                    # integrate numerically using simpson rule
                    # we could use x = r and skip dx, but the spacing is regular so it's probably better to do it this way
                    # simspon requires odd number of samples, what we have; just to be sure, we give the option for the
                    # even number of samples - for the first interval the trapezoidal rule is used and then simpson for the rest
                    val = integrate.simps(integrand, r, dx=ctrl['deltar'],
                                          even='last')
                    # add the result to the contribution of this potential
                    oc_contrib[-1] += prefactor * syst['dens']['num'][i] * \
                                      syst['dens']['num'][j] * val
                    # end for j in range(ctrl['ncomponents'])
                    # end for i in range(ctrl['ncomponents'])
        # end if (potential['pot_type'] == 'coulomb')

        # ****************************************

        elif (potential['pot_type'] == 'chg_inddip'):
            # since the analytic expression for dU_{chg_inddip}/dr is known, it's better to use
            # it directly in the evaluation - it's -4 U(chg_inddip)/r
            # dU_{chg_inddip}/dr = 4 (bjerrum_length * qi^2 * alphaj + bjerrum_length * qj^2 * alphai) / (2 r^5) = -4 * U(chg_inddip)/r
            # the expression for A
            # A = -1/kT dU/dr g r^3 dr
            # can be then simplified to (interaction energy is in kT units, so the
            # prefactor 1/kT cancels out) and
            # A_{chg_inddip} = 4 * U(chg_inddip) * g * r^2 dr
            # the resulting integral is then evaluated numerically

            for i in range(syst['ncomponents']):
                for j in range(syst['ncomponents']):
                    integrand = 4.0 * U_ij_individual[pot_index][i, j] * g_r_ij[
                        i, j] * r ** 2

                    # integrate numerically using simpson rule
                    # we could use x = r and skip dx, but the spacing is regular so it's probably better to do it this way
                    # simspon requires odd number of samples, what we have; just to be sure, we give the option for the
                    # even number of samples - for the first interval the trapezoidal rule is used and then simpson for the rest
                    val = integrate.simps(integrand, r, dx=ctrl['deltar'],
                                          even='last')
                    # add the result to the contribution of this potential
                    oc_contrib[-1] += prefactor * syst['dens']['num'][i] * \
                                      syst['dens']['num'][j] * val
                    # end for j in range(ctrl['ncomponents'])
                    # end for i in range(ctrl['ncomponents'])
        # end if (potential['pot_type'] == 'chg_inddip')

        # ****************************************

        elif (potential['pot_type'] == 'lj'):
            # since the analytic expression for dU_{LJ}/dr is known, it's better to use
            # it directly in the evaluation
            # dU_{lj}/dr = -24 \epsilon / r [ 2(sigma/r)^{12} - (sigma/r)^6 ]
            # the expression for A
            # A = -1/kT dU/dr g r^3 dr
            # can be then simplified to (epsilon is in kT units, so the
            # prefactor 1/kT cancels out)
            # A_{lj} =  24 \epsilon g r^2 [ 2(sigma/r)^{12} - (sigma/r)^6 ] dr
            # the resulting integral is then evaluated numerically

            for i in range(syst['ncomponents']):
                for j in range(syst['ncomponents']):
                    # calculate the integrand according to the expression above
                    integrand = 24 * potential['eps_ij'][i, j] * r ** 2 * \
                                g_r_ij[i, j] * (
                                2 * (potential['sigma_ij'][i, j] / r) ** 12 - (
                                potential['sigma_ij'][i, j] / r) ** 6)

                    # integrate numerically using simpson rule
                    # we could use x = r and skip dx, but the spacing is regular so it's probably better to do it this way
                    # simspon requires odd number of samples, what we have; just to be sure, we give the option for the
                    # even number of samples - for the first interval the trapezoidal rule is used and then simpson for the rest
                    val = integrate.simps(integrand, r, dx=ctrl['deltar'],
                                          even='last')
                    # add the result to the contribution of this potential
                    oc_contrib[-1] += prefactor * syst['dens']['num'][i] * \
                                      syst['dens']['num'][j] * val
                    # end for j in range(ctrl['ncomponents'])
                    # end for i in range(ctrl['ncomponents'])
        # end if (potential['pot_type'] == 'lj')

        # ****************************************

        elif (potential['pot_type'] == 'pmf'):
            # the dU_{pmf}/dr was evaluated numerically during reading of the parameters
            # it's used directly in the evaluation
            # the expression for A
            # A = -1/kT dU/dr g r^3 dr
            # U is in kT units, so the
            # prefactor 1/kT cancels out
            # A_{lj} =  dU(pmf)/dr g r^3 dr
            # the resulting integral is then evaluated numerically

            for i in range(syst['ncomponents']):
                for j in range(syst['ncomponents']):
                    # calculate the integrand according to the expression above
                    # integrand = -dU_ij_individual[pot_index][i,j] * g_r_ij[i,j] * r**3
                    # it doesn't work very well due to large dynamic range; let's try the other route, using the dg/dr
                    # firstly calculate the dg(pmf)/dr
                    # not using diff - not precise enough
                    # integrand = zeros(ctrl['npoints'])
                    # integrand[1:] = diff(modMayerFuncContrib[pot_index][i,j])/ ctrl['deltar']
                    # using gradient
                    integrand = np.gradient(modMayerFuncContrib[pot_index][i, j],
                                         ctrl['deltar'])
                    # calculate the product of remaining contributions to the total pair correlation function
                    # contributions of other pair potentials
                    for pot_index_exc in range(len(parm)):
                        if (pot_index_exc != pot_index):
                            integrand *= modMayerFuncContrib[pot_index_exc][
                                i, j]
                            # print("contribution", pot_index_exc, i, j, dr)
                    # contribution of the gamma function
                    # integrand *= exp(G_r_ij[i,j])
                    integrand *= G_term_ij[i, j]
                    # has to be modified to support also PY, ...
                    # and now finalize the integrand
                    integrand *= r ** 3

                    # integrate numerically using simpson rule
                    # we could use x = r and skip dx, but the spacing is regular so it's probably better to do it this way
                    # simspon requires odd number of samples, what we have; just to be sure, we give the option for the
                    # even number of samples - for the first interval the trapezoidal rule is used and then simpson for the rest
                    val = integrate.simps(integrand, r, dx=ctrl['deltar'],
                                          even='last')

                    # add the result to the contribution of this potential
                    oc_contrib[-1] += prefactor * syst['dens']['num'][i] * \
                                      syst['dens']['num'][j] * val
                    # end for j in range(ctrl['ncomponents'])
                    # end for i in range(ctrl['ncomponents'])
        # end if (potential['pot_type'] == 'pmf')

        # ****************************************

        else:
            print(
                "unsupported potential %s encountered!" % potential['pot_type'])
            sys.exit(1)

        # ****************************************

        # add the last contribution to the total osmotic coefficient
        osm_coeff += oc_contrib[-1]

    # end for potential in parm

    print("\tosmotic coefficient\t\t%8.5f" % osm_coeff)

    print("\t\tcontributions of individual potentials")
    print("\t\tpotential title given in brackets")
    for index in range(len(oc_contrib)):
        # print individual contributions
        # calculate the coefficient
        print("\t\t%s\t\t\t%8.5f (%s)" % (
        parm[index]['pot_title'], oc_contrib[index], parm[index]['pot_type']))
    print("")

    # return osm_coeff


# end def osmotic_coeff()

# **********************************************************************************************  

def excess_chempot(ctrl, syst, const, r, h_r, gam_r, c_sr, index, parm):
    """
      calculates the excess potential divided by kT
      exponentiation leads to activity coefficient

      currently only HNC approximation is supported

      for binary systems with coulomb interaction (index>1), calculate the mean activity coefficient
      index > -1 - index for the Coulomb in parm array
    """

    muex = []

    # contribution of every component is evaluated separately
    # \beta mu_i^{ex} = \sum_i \rho_i \int [ h(r) * \gamma(r) / 2 - c^s(r) ] 4 \pi r^2 dr

    for i in range(syst['ncomponents']):
        result = 0.0
        for j in range(syst['ncomponents']):
            prefactor = 4.0 * pi * syst['dens']['num'][j]
            integrand = 0.5 * h_r[i, j] * gam_r[i, j] - c_sr[i, j]
            result += prefactor * integrate.simps(integrand * r ** 2, r,
                                                  dx=ctrl['deltar'],
                                                  even='last')
            # part_result = prefactor * int_simpson(integrand * r**2, r, dx=ctrl['deltar'], even='last')
            # print("\t\t\texcess chem pot combination %u-%u contrib %f" % (i, j, part_result))
            # result += part_result
        # print(result)
        # append the result to the array
        muex.append(result)

    act_coeff = exp(muex)

    print("\texcess chemical potential (using sr-c(r))")
    print("\t\tmu/kT\t\t\t"),
    for i in range(syst['ncomponents']):
        print("%f" % muex[i]),
    print("")
    print("\tactivity coefficients\t")
    print("\t\texp(mu/kT)\t\t"),
    for i in range(syst['ncomponents']):
        print("%f" % act_coeff[i]),
    print("")
    if (index > -1 and syst['ncomponents'] == 2):
        # we have charged system, therefore we should calculate mean activity coeff
        # g^v = g_1^{v1}g_2^{v2}g_3^{v3}
        sum_stech = abs(parm[index]['charge'][0]) + abs(
            parm[index]['charge'][1])
        prod_coeff = (
        act_coeff[0] ** abs(parm[index]['charge'][1]) * act_coeff[1] ** abs(
            parm[index]['charge'][0]))
        mean = prod_coeff ** (1.0 / sum_stech)
        print("\t\tmean\t\t\t%f" % mean)
        print("")


# end def excess_mu()

# **********************************************************************************************  

def compressibility(ctrl, syst, const, r, c_sr):
    """
      calculates isothermal compressibility and excess isothermal compressibility
    """

    if (syst['dens']['totnum'] == 0.0):
        # infinite dilution
        chi_ex = 1.0
        chi_ex_r = 1.0
        chi = inf
        chi_r = 0.0
        chi_id = inf
        chi_id_r = 0.0
    else:
        # calculate the prefactor 4 pi / rho
        prefactor = 4.0 * pi / syst['dens']['totnum']
        # reciprocal of the excess compressibility
        # initialize to 1
        chi_ex_r = 1.0
        chi_id = 1.0e-7 / (const.kT * syst['dens']['totnum'])
        chi_id_r = 1.0e7 * const.kT * syst['dens']['totnum']
        # perform the calculation
        # chi_ex_r = 1 - 1/\rho \sum_i \sum_j \rho_i \rho_j \int c_sr 4 \pi r^2 dr
        # 4 \pi / \rho is in the prefactor
        # integrate numerically using simpson rule
        # we could use x = r and skip dx, but the spacing is regular so it's probably better to do it this way
        # simspon requires odd number of samples, what we have; just to be sure, we give the option for the
        # even number of samples - for the first interval the trapezoidal rule is used and then simpson for the rest
        for i in range(syst['ncomponents']):
            for j in range(syst['ncomponents']):
                contrib = prefactor * syst['dens']['num'][i] * \
                          syst['dens']['num'][j] * integrate.simps(
                    c_sr[i, j] * r ** 2, r, dx=ctrl['deltar'], even='last')
                chi_ex_r -= contrib
                # print i,j,contrib

        chi_ex = 1.0 / chi_ex_r

        # 1/chi_ex = chi_id/chi; chi_id = 1/\rho kT
        # chi = chi_id chi_ex
        # 1/chi = 1/(chi_ex * chi_id)
        chi = chi_ex * chi_id
        chi_r = chi_id_r / chi_ex
    # end if (syst['dens']['totnum'] == 0.0)

    print("\tisothermal compressibility (using sr-c(r))")
    print("\t\texcess chi, chi^(-1)\t%f    %f" % (chi_ex, chi_ex_r))
    print("\t\tideal chi, chi^(-1)\t%.5e %f" % (chi_id, chi_id_r))
    print("\t\tabsolute, chi, chi^(-1)\t%.5e %f" % (chi, chi_r))
    print("")