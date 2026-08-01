# Anaheim (import required)

The Anaheim instance is not bundled. Import it from the TNTP repository
(github.com/bstabler/TransportationNetworks, Anaheim_net.tntp and
Anaheim_trips.tntp) with the bundled converter:

    python -m taplab.converters.gmns_tntp tntp2gmns Anaheim_net.tntp Anaheim_trips.tntp tapbench/anaheim

Then run `taplab stats tapbench/anaheim` and `taplab validate tapbench/anaheim`;
TAPValidate computes and publishes all statistics directly from the imported
instance.
