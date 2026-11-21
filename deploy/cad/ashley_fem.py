"""Linear static elasticity on second-order tetrahedra (gmsh's 10-node tetrahedron), for `ashley_fea`: an isotropic
material, fixed nodes, nodal forces. Millimetres, newtons and megapascals throughout.

Node order is gmsh's: the four corners, then the midpoints of edges 0-1, 1-2, 2-0, 3-0, 3-2, 3-1. Stiffness is integrated
with the four-point rule, exact for this element. Stress is evaluated at each element's ten nodes and averaged over the
elements that share a node, so a peak is a nodal value, not a smoothed one over a region."""

from typing import Any, NamedTuple

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve

_A, _B = 0.5854101966249685, 0.1381966011250105
GAUSS = np.array([[_A, _B, _B, _B], [_B, _A, _B, _B], [_B, _B, _A, _B], [_B, _B, _B, _A]])
"""Barycentric coordinates of the four integration points, each of weight a quarter of the element's volume."""
EDGES = ((0, 1), (1, 2), (2, 0), (3, 0), (3, 2), (3, 1))
NODE_BARY = np.vstack([np.eye(4), [[0.5 if i in e else 0.0 for i in range(4)] for e in EDGES]])
"""Barycentric coordinates of an element's ten nodes."""
TOLERANCE = 1e-6
"""Largest relative residual `|K u - f| / |f|` over the free nodes that still counts as solved."""


class Solution(NamedTuple):
    displacement: Any
    """(n, 3) displacement of each node, mm."""
    von_mises: Any
    """(n,) von Mises stress at each node, MPa, averaged over the elements sharing it."""
    residual: float


def _shape_gradients(bary: Any) -> Any:
    """d N_i / d L_k for the ten shape functions at barycentric point `bary` (4,), as (10, 4)."""
    grad = np.zeros((10, 4))
    for i in range(4):
        grad[i, i] = 4 * bary[i] - 1
    for row, (i, j) in enumerate(EDGES, 4):
        grad[row, i], grad[row, j] = 4 * bary[j], 4 * bary[i]
    return grad


def _physical_gradients(corners: Any) -> tuple[Any, Any]:
    """For elements with `corners` (ne, 4, 3): d L_k / d x as (ne, 4, 3) and each element's volume."""
    edge = corners[:, 1:] - corners[:, :1]
    inverse = np.linalg.inv(edge)
    rest = inverse.transpose(0, 2, 1)
    grad = np.concatenate([-rest.sum(axis=1, keepdims=True), rest], axis=1)
    return grad, np.abs(np.linalg.det(edge)) / 6


def _strain_matrix(grad_l: Any, bary: Any) -> Any:
    """B (ne, 6, 30) at barycentric point `bary`: engineering strain (xx, yy, zz, yz, xz, xy) from the 30 nodal displacements."""
    grad_n = np.einsum("nk,ekd->end", _shape_gradients(bary), grad_l)
    b = np.zeros((len(grad_l), 6, 30))
    for node in range(10):
        gx, gy, gz = grad_n[:, node, 0], grad_n[:, node, 1], grad_n[:, node, 2]
        c = 3 * node
        b[:, 0, c], b[:, 1, c + 1], b[:, 2, c + 2] = gx, gy, gz
        b[:, 3, c + 1], b[:, 3, c + 2] = gz, gy
        b[:, 4, c], b[:, 4, c + 2] = gz, gx
        b[:, 5, c], b[:, 5, c + 1] = gy, gx
    return b


def elasticity(young: float, poisson: float) -> Any:
    """The 6x6 isotropic stiffness matrix for engineering strain."""
    lam = young * poisson / ((1 + poisson) * (1 - 2 * poisson))
    mu = young / (2 * (1 + poisson))
    d = np.zeros((6, 6))
    d[:3, :3] = lam
    d[range(3), range(3)] += 2 * mu
    d[range(3, 6), range(3, 6)] = mu
    return d


def _assemble(nodes: Any, tets: Any, d: Any) -> Any:
    grad_l, volume = _physical_gradients(nodes[tets[:, :4]])
    ke = np.zeros((len(tets), 30, 30))
    for point in GAUSS:
        b = _strain_matrix(grad_l, point)
        ke += np.einsum("eji,jk,ekl->eil", b, d, b) * (volume / 4)[:, None, None]
    dof = (3 * tets[:, :, None] + np.arange(3)).reshape(len(tets), 30)
    rows = np.repeat(dof, 30, axis=1).reshape(-1)
    cols = np.tile(dof, (1, 30)).reshape(-1)
    size = 3 * len(nodes)
    return coo_matrix((ke.reshape(-1), (rows, cols)), shape=(size, size)).tocsc()


def _nodal_von_mises(nodes: Any, tets: Any, d: Any, u: Any) -> Any:
    grad_l, _ = _physical_gradients(nodes[tets[:, :4]])
    ue = u[tets].reshape(len(tets), 30)
    total, count = np.zeros(len(nodes)), np.zeros(len(nodes))
    for local, bary in enumerate(NODE_BARY):
        s = np.einsum("ij,ejk,ek->ei", d, _strain_matrix(grad_l, bary), ue)
        vm = np.sqrt(0.5 * ((s[:, 0] - s[:, 1]) ** 2 + (s[:, 1] - s[:, 2]) ** 2 + (s[:, 2] - s[:, 0]) ** 2)
                     + 3 * (s[:, 3] ** 2 + s[:, 4] ** 2 + s[:, 5] ** 2))
        np.add.at(total, tets[:, local], vm)
        np.add.at(count, tets[:, local], 1)
    return total / np.maximum(count, 1)


def solve(nodes: Any, tets: Any, young: float, poisson: float, fixed: Any, forces: Any) -> Solution:
    """Displacements and nodal von Mises stress of the mesh (`nodes` (n, 3), `tets` (ne, 10) indices) with the nodes
    in `fixed` held in all three directions and `forces` (n, 3) in newtons applied. The residual is measured on the
    solved system, never assumed; a caller decides what is too large (`TOLERANCE`)."""
    d = elasticity(young, poisson)
    stiffness = _assemble(nodes, tets, d)
    held = np.zeros(len(nodes), dtype=bool)
    held[fixed] = True
    free = np.flatnonzero(~np.repeat(held, 3))
    load = forces.reshape(-1)[free]
    k = stiffness[free][:, free].tocsc()
    u = np.zeros(3 * len(nodes))
    u[free] = spsolve(k, load, permc_spec="MMD_AT_PLUS_A")
    norm = np.linalg.norm(load)
    residual = float(np.linalg.norm(k @ u[free] - load) / norm) if norm > 0 else float("nan")
    u = u.reshape(-1, 3)
    return Solution(u, _nodal_von_mises(nodes, tets, d, u), residual)
