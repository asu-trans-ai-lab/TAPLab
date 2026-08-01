# TAPBench data provenance and licensing

TAPLab's MIT license covers the code only. Every bundled network keeps its own
provenance, citation, and redistribution terms, recorded here with SHA-1
checksums (first 16 hex digits) of the bundled tables.

| Instance | Provenance | Citation / terms |
| --- | --- | --- |
| diagnostic/two_route | Constructed for TAPLab | CC0; no restrictions |
| sioux_falls | TNTP TransportationNetworks (bstabler) via CompressedTAP GMNS conversion | LeBlanc et al. (1975); research use per the TransportationNetworks repository |
| anaheim | TNTP TransportationNetworks (bstabler), imported 2026-07-31 | research use per the TransportationNetworks repository |
| chicago_sketch | TNTP TransportationNetworks (bstabler) via GMNSforTAP conversion; coordinates from the CompressedTAP conversion | Eash, Chon, Lee & Boyce (1979); research use per the TransportationNetworks repository |
| chicago_regional | CMAP Chicago Regional via TNTP lineage; GMNS conversion from the CompressedTAP experiments | research use per the TransportationNetworks repository |
| philadelphia | TNTP TransportationNetworks Philadelphia via the TAsK distribution | research use per the TransportationNetworks repository |
| arc_atlanta_super600 | ARC activity-based model (licensed) | NOT bundled and NOT redistributable; local import only via taplab.converters.import_arc_super600 |

## Checksums

### diagnostic/two_route
- `node.csv`: `bce4f751547826ad`
- `link.csv`: `3085a30e1ae77379`
- `demand.csv`: `5917a8f57fe075d5`

### sioux_falls
- `node.csv`: `bdad10f06c340845`
- `link.csv`: `48a92d756d26c02e`
- `demand.csv`: `1806d76d2e3fc39c`

### anaheim
- `node.csv`: `5773fd79d64cebf2`
- `link.csv`: `d4ce99ee3e3e3ed1`
- `demand.csv`: `cbf87e9fc08cd970`

### chicago_sketch
- `node.csv`: `c37520ed04496b4e`
- `link.csv`: `ce5244a1de4e2f31`
- `demand.csv`: `8291eb63f86f658b`

### chicago_regional
- `node.csv`: `3a699ce492209a5b`
- `link.csv`: `2d43c5eec785d4d6`
- `demand.csv.gz`: `b11a1a4907be7609`

### philadelphia
- `node.csv`: `3e62e451c1beacc8`
- `link.csv`: `2154022676f599ab`
- `demand.csv.gz`: `3451d35a39cf6ca4`
