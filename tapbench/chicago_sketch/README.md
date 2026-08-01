# Chicago Sketch

The CATS sketch-planning network in TAPLab's compact GMNS-compatible
representation (387 centroid nodes, 933 nodes, 2,950 links; statistics are
computed by `taplab stats`, not hard-coded here). Links touching exactly one
centroid are typed `centroid_connector`. `reference/link_performance.csv`
carries the TNTP best-known UE volumes. This is the primary cross-solver
verification instance: the GMNS -> TNTP -> tap-b Algorithm B -> GMNS pathway
reproduces the best-known flows to within ~0.07%.
