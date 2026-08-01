# Sioux Falls

The classic 24-zone / 76-link academic instance in TAPLab's compact
GMNS-compatible representation. Centroids coincide with physical nodes
(node_type=centroid, node_id = zone_id), so no connectors are needed.
`reference/link_performance.csv` carries the TNTP best-known UE volumes;
`taplab run sioux_falls --solver reference_fw` reproduces them (see the
generated report for RMSE).
