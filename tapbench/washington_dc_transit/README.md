# Washington DC City — transit service layer

GTFS-derived transit service network for WMATA, DC Circulator, and DC
Streetcar (public GTFS feeds), built with gtfs2gmns following the
six-link-type transit GMNS taxonomy (physical sta2sta, entrance/exit sta2r,
service r2r, transfer walking), joined to the same 179 TAZ centroids through
z2sta walk-access links (<= 1 mile at 2 mph, 5-minute penalty beyond 0.5
mile) and carrying a synthetic transit OD table (15% of the driving OD).
Midday 1200-1300 service hour. Uncongested: all-or-nothing is the exact
equilibrium (certified at gap 0).
