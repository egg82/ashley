"""Linear static elasticity on second-order tetrahedra for `ashley_fea`, by scikit-fem: an isotropic material, fixed
nodes, nodal forces. Millimetres, newtons and megapascals throughout.

The mesh comes from gmsh as 10-node tetrahedra with straight edges (`Mesh.SecondOrderLinear`), so scikit-fem's own quadratic
dofs sit exactly on gmsh's nodes and the two are matched by position. Stress is the von Mises value of the six stress
components, each projected onto the quadratic space (continuous, so a node has one value, not one per element)."""

import logging
from typing import Any, NamedTuple

import numpy as np
from scipy.sparse.linalg import spsolve
from scipy.spatial import cKDTree
from skfem import Basis, ElementTetP2, ElementVector, MeshTet, asm, condense
from skfem.models.elasticity import lame_parameters, linear_elasticity

TOLERANCE = 1e-6
"""Largest relative residual `|K u - f| / |f|` over the free dofs that still counts as solved."""
MATCH = 1e-6
"""Relative distance a gmsh node may be from the dof it is matched to."""
logging.getLogger("skfem").setLevel(logging.ERROR)
COMPONENTS = ((0, 0), (1, 1), (2, 2), (0, 1), (1, 2), (0, 2))


class Solution(NamedTuple):
    displacement: Any
    """(n, 3) displacement of each node, mm."""
    von_mises: Any
    """(n,) von Mises stress at each node, MPa."""
    residual: float


def _node_dofs(nodes: Any, tets: Any) -> tuple[Any, Any, Any, Any]:
    """The scalar and vector quadratic bases of the gmsh `tets` (ne, 10) over `nodes` (n, 3), and for each gmsh node its
    scalar dof and its three vector dofs. Raises ValueError for a node that no dof sits on."""
    corners = np.unique(tets[:, :4])
    renumber = np.zeros(len(nodes), dtype=int)
    renumber[corners] = np.arange(len(corners))
    mesh = MeshTet(nodes[corners].T, renumber[tets[:, :4]].T)
    scalar, vector = Basis(mesh, ElementTetP2()), Basis(mesh, ElementVector(ElementTetP2()))
    order = np.concatenate([scalar.nodal_dofs[0], scalar.edge_dofs[0]])
    by_scalar = np.empty((3, scalar.N), dtype=int)
    by_scalar[:, order] = np.concatenate([vector.nodal_dofs, vector.edge_dofs], axis=1)
    gap, dof = cKDTree(scalar.doflocs.T).query(nodes)
    if gap.max() > MATCH * max(1.0, float(np.ptp(nodes, axis=0).max())):
        raise ValueError("a mesh node is not on a second-order dof: the mesh has curved edges")
    return scalar, vector, dof, by_scalar[:, dof]


def _von_mises(scalar: Any, vector: Any, u: Any, lam: float, mu: float) -> Any:
    """Von Mises stress at each scalar dof, from the gradient of the displacement `u` (a vector dof array)."""
    grad = vector.interpolate(u).grad
    strain = 0.5 * (grad + grad.transpose(1, 0, 2, 3))
    trace = strain[0, 0] + strain[1, 1] + strain[2, 2]
    stress = 2 * mu * strain + lam * trace * np.eye(3)[:, :, None, None]
    xx, yy, zz, xy, yz, xz = (scalar.project(stress[k]) for k in COMPONENTS)
    return np.sqrt(0.5 * ((xx - yy) ** 2 + (yy - zz) ** 2 + (zz - xx) ** 2) + 3 * (xy ** 2 + yz ** 2 + xz ** 2))


def solve(nodes: Any, tets: Any, young: float, poisson: float, fixed: Any, forces: Any) -> Solution:
    """Displacements and nodal von Mises stress of the mesh (`nodes` (n, 3), `tets` (ne, 10) indices into them) with the
    nodes in `fixed` held in all three directions and `forces` (n, 3) in newtons applied. The residual is measured on the
    solved system, never assumed; a caller decides what is too large (`TOLERANCE`)."""
    lam, mu = lame_parameters(young, poisson)
    scalar, vector, dof, at = _node_dofs(nodes, tets)
    load = np.zeros(vector.N)
    load[at] = forces.T
    system, rhs, _, free = condense(asm(linear_elasticity(lam, mu), vector), load, D=np.unique(at[:, fixed]))
    u = np.zeros(vector.N)
    u[free] = spsolve(system.tocsc(), rhs, permc_spec="MMD_AT_PLUS_A")
    norm = np.linalg.norm(rhs)
    residual = float(np.linalg.norm(system @ u[free] - rhs) / norm) if norm > 0 else float("nan")
    return Solution(u[at].T, _von_mises(scalar, vector, u, lam, mu)[dof], residual)
