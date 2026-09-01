When updating OPR game rules:
1. Identify all affected files (rules, costs, abilities, JS rendering)
2. Apply changes using ONLY straight ASCII quotes as Python delimiters
3. Run `pytest` and confirm all tests pass
4. Verify backend payload AND JS render layer both reflect the change
5. Summarize changes in a commit-ready message
