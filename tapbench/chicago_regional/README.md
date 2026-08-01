# Chicago Regional

Large-scale performance and path-coverage instance in TAPLab's compact
GMNS-compatible representation. Demand is bundled as `demand.csv.gz`.

Chicago Regional requires a specific distinction among (1) solver accuracy on
the supplied path pool, (2) adequacy of the supplied path pool, and (3)
convergence to full-network user equilibrium. A fixed-pool solution cannot be
described as a full-network equilibrium when positive-demand OD pairs have no
available path, so TAPLab reports OD coverage and route-richness statistics
(`taplab stats`) separately from solver convergence. Statistics are computed
from the imported instance, never hard-coded.
