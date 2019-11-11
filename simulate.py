import numpy as np
import pandas as pd
from adm import solveSDP, simplifyX
import time
import math
import scipy.linalg
from scipy import sparse
import sys
import cProfile
from termcolor import cprint 

if not sys.warnoptions:
    import warnings
    warnings.simplefilter("ignore")

def getA0s(D, n, dimension):
    constraints = []
    for i in range(len(D)):
        slack = n * len(D) + i
        constraint = {"V" : [1, -1], "I" : [slack, dimension-1], "J" : [slack, dimension-1]}
        for j in range(n):
            coord = i * n + j
            constraint["V"] += [1]
            constraint["I"] += [coord]
            constraint["J"] += [coord]
        constraints.append(constraint)
    return constraints

def getA1s(D, n, F):
    constraints = []
    for (y,z) in F:
        constraint = {"V": [], "I" : [], "J" : []}
        for i in range(n):
            if D[y][i] != D[z][i]:
                constraint["V"] += [1]
                constraint["I"] += [n*y + i]
                constraint["J"] += [n*z + i]
        constraints.append(constraint)
    return constraints

def getConstraints(D, E):
    F = []               # Cartesian product of inputs with different outputs
    n = len(D[0])                     # length of bit string
    dimension = len(D) * (n + 1) + 1  # dimension of matrix

    # Construct F
    for i in range(len(D)):
        for j in range(len(D)):
            if E[i] != E[j]:
                F.append((i,j))
    
    constraints = []
    constraints.extend(getA0s(D=D, n=n, dimension=dimension))
    constraints.extend(getA1s(D=D, n=n, F=F))

    b_0s = np.zeros((len(D), 1), dtype = np.float32) # vector of 0s
    b_1s = np.ones((len(F), 1), dtype = np.float32) # vector of 1s
    bs = np.concatenate((b_0s, b_1s), axis=0)

    C = sparse.csr_matrix(np.zeros((dimension, dimension)))
    C[- 1, - 1] = 1
    return constraints, bs, C

D = ['000','001', '110', '110', '111'] # inputs to Boolean function f
E = ['0', '1', '1', '1', '1']  # corresponding outputs to f
D = ['11', '10', '00', '01']
E = ['1', '1', '0', '1']

def getAllBitStrings(n):
    return [np.binary_repr(i, width=n) for i in range(2**n)]

def functionOR(bitstring):
    if '1' in bitstring:
        return '1'
    return '0'

def getE(bitstrings, function):
    return [function(bitstring) for bitstring in bitstrings]

def getORAll(n):
    D = getAllBitStrings(n)
    E = getE(D, functionOR)
    return D, E

def getORWorst(n):
    D = ['0'*n]
    E = ['0']
    for i in range(n):
        starting = '0' * (n-i-1) + '1' + '0' * i
        D.append(starting)
        E.append('1')
    return D, E

def wrapSDPSolver(D, E):
    constraints, b, C = getConstraints(D=D, E=E)
    X, iteration = solveSDP(constraints=constraints, b=b, C=C, accuracy=1e-6)
    getSpanProgram(X, D=D, E=E)
    return X[-1, -1], iteration

def calculateSDPSolverComplexity(iterations, getDandE, filename="", start=1):
    found_vals = []
    true_vals = []
    input_size = []
    run_time = []
    for i in range(start, iterations+1):
        print("Input size: {}".format(i))
        D, E = getDandE(i)

        print("D: {}".format(D))
        print("E: {}".format(E))

        starting_time = time.time()
        opt_val, iteration = wrapSDPSolver(D, E)
        t = time.time() - starting_time

        print("Obj. Func. Value: {}".format(opt_val))
        print("Num. Iterations: {}".format(iteration))
        print("Run Time: {}  \n".format(t))

        found_vals.extend([opt_val.real])
        true_vals.extend([math.sqrt(i)])
        input_size.extend([i])
        run_time.extend([t])

    resultsDF = pd.DataFrame(data = {'Empirical': found_vals, 'Analytical': true_vals, 'n': input_size, 'RunTime': run_time})

    if filename != "":
        resultsDF.to_csv(index=False, path_or_buf= "./figures/{}.csv".format(filename))

def getL(X, tolerance):
    vals, vecs = np.linalg.eig(X)
    L = np.zeros(X.shape, dtype = np.complex128)
    for k in range(len(vals)):
        val = vals[k]
        vec = vecs[:,k]
        ket_k = np.zeros((len(vals),1), dtype = np.complex128)
        ket_k[k,0] = 1
        scalar = np.complex128(np.sqrt(np.absolute(val)))
        L += scalar * ket_k.dot(vec.H)

    reconstructed_X = simplifyX(np.matrix(L).H.dot(L))
    assert (np.absolute(reconstructed_X - X) < tolerance).all()
    return np.matrix(L)

def checkL(L, D, E, tolerance=1e-3):
    n = len(D[0])
    LH = L.H
    for x_index in range(len(D)):
        x = D[x_index]
        fx = E[x_index]
        for y_index in range(x_index + 1, len(D)):
            y = D[y_index]
            fy = E[y_index]
            should_be = 1 - (fx == fy)
            summation = 0
            for i in range(len(x)):
                xi = np.zeros((1,len(D)*n))
                yi = np.zeros((len(D) * n, 1))
                xi[0,x_index*n + i] = 1
                yi[y_index * n + i,0] = 1
                vxi = xi.dot(LH)
                #print("vxi", vxi)
                #print("toher_vxi", L.H[n*x_index+i, :])
                vyi = L.dot(yi)
                if x[i] != y[i]:
                    summation += vxi.dot(vyi)
            assert np.absolute(should_be - summation) < tolerance

def getSpanProgram(X, D, E, tolerance=1e-4):
    little_X = X[:-len(D)-1, :-len(D)-1]
    L = getL(X=little_X, tolerance=tolerance)
    n = len(D[0])
    V = []
    F0_idx = []
    for i in range(len(D)):
        if E[i] == '0':
            F0_idx.append(i)
    for x_index in F0_idx:
        x = D[x_index]
        vx = []
        for i in range(n):
            not_xi = 1 - eval(x[i])
            not_xi_vec = [0,0]
            not_xi_vec[not_xi] = 1
            vxi = np.round(np.real(L.H[n*x_index + i,:]))
            not_xi_times_vxi = np.kron(not_xi_vec, vxi)
            vx += np.asarray(not_xi_times_vxi).tolist()[0]
        V.append(vx)
    checkL(L=L, D=D, E=E)
    target = np.ones((len(F0_idx),1))
    checkSpanProgram(D=D, E=E, V=V, target=target)
    return V, target

def checkSpanProgram(D, E, V, target, tolerance = 1e-4):
    V = np.array(V)
    n = len(D[0])
    vxi_length = n *len(D)
    for y_index in range(len(D)):
        y = D[y_index]
        I = []
        for i in range(n):
            start_index = (i*2 + eval(y[i])) *vxi_length
            current_subblock = V[:,start_index:start_index+vxi_length]
            I += current_subblock.tolist()[0]
        I = np.matrix(I)
        target = np.matrix(target)
        linear_combo, residuals, rank, s = np.linalg.lstsq(a=I, b=target)
        residual = sum((np.matmul(I, linear_combo) - target) ** 2)[0,0]
        assert (residual < tolerance) == (E[y_index] == '1')
    return True

def testSDPSolverOnOR(iterations=5, accuracy = 2):
    all_passed = True
    for n in range(1, iterations + 1):
        print("Testing SDP solver on OR for n = {}...".format(n), end=" ")
        D, E = getORAll(n)
        received, iteration = wrapSDPSolver(D, E)
        expected = np.sqrt(n)
        if round(received, accuracy) == round(expected, accuracy):
            cprint("passed :)", "green")
        else:
            all_passed = False
            cprint("failed :(", "red")
            cprint("Expected: {}".format(expected), "green")
            cprint("Received: {}".format(received), "red")

    if all_passed:
        cprint("Tests passed :)", "green")
    else:
        cprint("Tests failed :(", "red")

if __name__ == '__main__':
    pass
    #testSDPSolverOnOR()

#cProfile.run("calculateSDPSolverComplexity(20, getORWorst)", sort = "time")
#cProfile.run("calculateSDPSolverComplexity(6, getORAll)", sort = "time")
#calculateSDPSolverComplexity(6, getORAll, "output_all_or")
#calculateSDPSolverComplexity(20, getORWorst, "output_worst_or")

cProfile.run("calculateSDPSolverComplexity(6, getORAll)", sort="time")
#calculateSDPSolverComplexity(2, getORAll, start=2)