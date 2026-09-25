"""Demo: Pythia8 event generation plus FastJet anti-kt jet finding.

Run after installing/loading the relevant hepyy packages, for example:

    hepyy install fastjet pythia8 hepyy-utils
    python examples/demo_pythia_fastjet.py

If the packages are already shell-loaded with module load, the explicit
hepyy.load calls below are harmless.
"""

import hepyy

from hepyy_utils.pythia import PythiaConfig, create_pythia


hepyy.load("fastjet")
config = PythiaConfig.pp_hard_qcd(ecm=13000.0, pthat_min=20.0)
pythia = create_pythia(config, load=True)

import cppyy
import fastjet


PseudoJetVec = cppyy.gbl.std.vector[fastjet.PseudoJet]

jet_radius = 0.4
pt_min = 20.0
jet_def = fastjet.JetDefinition(fastjet.antikt_algorithm, jet_radius)

n_events = 100
n_jets_total = 0
leading_pts: list[float] = []

print(f"Generating {n_events} Pythia8 pp dijet events, anti-kt R={jet_radius}")

for i_event in range(n_events):
    if not pythia.next():
        continue

    particles = PseudoJetVec()
    event = pythia.event
    for index in range(event.size()):
        particle = event[index]
        if particle.isFinal() and particle.isVisible():
            particles.push_back(
                fastjet.PseudoJet(
                    particle.px(),
                    particle.py(),
                    particle.pz(),
                    particle.e(),
                )
            )

    if particles.size() == 0:
        continue

    cluster_sequence = fastjet.ClusterSequence(particles, jet_def)
    jets = fastjet.sorted_by_pt(cluster_sequence.inclusive_jets(pt_min))
    n_jets_total += len(jets)
    if jets:
        leading_pts.append(jets[0].pt())

    if i_event < 3 and jets:
        print(f"Event {i_event + 1}: {int(particles.size())} particles, {len(jets)} jets")
        for i_jet, jet in enumerate(jets):
            n_constituents = len(cluster_sequence.constituents(jet))
            print(
                f"  jet {i_jet}: pt={jet.pt():.1f} eta={jet.eta():.2f} "
                f"phi={jet.phi():.2f} n_const={n_constituents}"
            )

pythia.stat()

print(f"Processed {n_events} events")
print(f"Total jets found with pt > {pt_min} GeV: {n_jets_total}")
print(f"Mean jets per event: {n_jets_total / n_events:.2f}")
if leading_pts:
    print(f"Leading jet mean pt: {sum(leading_pts) / len(leading_pts):.1f} GeV")
    print(f"Leading jet max pt: {max(leading_pts):.1f} GeV")
