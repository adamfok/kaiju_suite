# Joint Tool

QC for joints. Shows what's wrong with your rigging and fixes it.

## QC tab

Run the joint checks on selected joints, with options saved per user:

- **skinned** — Check that the selected joints have skinCluster influences.
- **normalized** — All joint weights sum to 1.0. 
- **influence_count** — Maximum number of influences.
- **small_weights** — Any weight below the threshold (default 0.01).
- **unused** — Unused influences.

All checks are optional; to disable a check, right-click its header and disable it.

The QC tab has only one tab: "QC", because this one is empty for now.