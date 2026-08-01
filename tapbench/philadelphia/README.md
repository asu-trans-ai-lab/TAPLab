# Philadelphia (import required)

The Philadelphia instance (approximately 40,000 links) is not bundled. Import
it from the TNTP repository (github.com/bstabler/TransportationNetworks,
Philadelphia_net.tntp and Philadelphia_trips.tntp) with:

    python -m taplab.converters.gmns_tntp tntp2gmns Philadelphia_net.tntp Philadelphia_trips.tntp tapbench/philadelphia

Philadelphia serves large-scale scalability and transferability testing
(benchmark track B4). All statistics are computed by `taplab stats`.
