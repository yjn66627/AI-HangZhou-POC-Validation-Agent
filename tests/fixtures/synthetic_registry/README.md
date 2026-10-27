# Independent synthetic registry test data

Every file is SYNTHETIC_DEMO_DATA. This case, query, IDs and policy were authored independently for public loading, isolation, and rejection tests. They were not reconstructed from private expected values or real frozen responses.

The arbitrary rule allows CLARIFY; the canned runner currently returns ANSWER, so the evaluator must reject that output. A completed run does not imply that the result met the rule or that an actual enterprise experiment ran.

Tests pass these files explicitly to CaseRegistry. They are never mounted as the default registry and never used to make historical tests pass. The inherited private_files argument and PRIVATE_GOLD source label designate the evaluator-side interface; these particular test values are intentionally public synthetic data.
