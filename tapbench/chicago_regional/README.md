# Chicago Regional (import required)

The Chicago Regional instance (39,018 links; approximately 40 MB of OD demand)
is not bundled in the repository. Import it from the TNTP repository
(github.com/bstabler/TransportationNetworks, ChicagoRegional_net.tntp and
ChicagoRegional_trips.tntp) with:

    python -m taplab.converters.gmns_tntp tntp2gmns ChicagoRegional_net.tntp ChicagoRegional_trips.tntp tapbench/chicago_regional

Chicago Regional requires a specific distinction among (1) solver accuracy on
the supplied path pool, (2) adequacy of the supplied path pool, and (3)
convergence to full-network user equilibrium. A fixed-pool solution cannot be
described as a full-network equilibrium when positive-demand OD pairs have no
available path, so TAPLab reports OD coverage and route-richness statistics
(`taplab stats`) separately from solver convergence.
