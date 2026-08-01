# Washington DC City — driving layer

OSM-derived DC city driving network from the GMNS_Plus dataset (Global
Dataset Project) with 179 TAZ centroids and the dataset's synthetic OD
demand. The importer (taplab.converters.import_dc_multimodal) restricts the
physical network to its giant strongly connected component and re-snaps
orphaned zone connectors to the nearest SCC node, so the instance passes
V1-V8 with zero dropped demand and solves without artificial arcs.
Certified: tap-b Algorithm B at an independently recomputed gap of 4.4e-6.
