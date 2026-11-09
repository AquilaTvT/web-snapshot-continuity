# Publication permissions and current identity

Current-key reads on native MinIO: owner credentials can delete a version despite the bucket-policy control; compliance retention protects the data version but not the delete marker. A restricted publisher cannot remove B, while copying old A publishes a new ID. Symbols are row-local aliases, not time or numeric order. These are finite operation traces, not production incidence or an audit of every API.

Copy this whole directory. Run `python3 -m pip install -r requirements.txt`, `python3 derive.py --self-test`, then `python3 plot.py`. No parent imports or network access is used by derivation/rendering. `plot-data.csv` contains exact IDs, response hashes, request indices, principals and monotone windows. `version-id-map.csv` makes the display aliases reversible. The complete raw trace and cryptographic hashes stay beside the figure.

Rows 1 and 2 use owner credentials; rows 3 and 4 use an IAM-restricted publisher. They do not compare equivalent authorization conditions. The first row is a failed enforcement control, not a claim that AWS bucket policies are bypassed. The second row includes a verified WORM rejection before marker insertion/removal. Read the policies and operations in the trace before extrapolating.
