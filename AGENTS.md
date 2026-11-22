# LocalMind contributor guidance

Read the [product requirements](docs/DEVCREW_MASTER_MISSION.md),
[quality gates](docs/QUALITY_GATES.md), [recorded user failures](docs/USER_FAILURES.md),
[Russian STT scenarios](docs/STT_TEST_SET.csv) and
[conference notes](docs/CONFERENCE_2026_NOTES.md) before changing behavior.

- Keep the application runnable. Use small isolated commits and check changes before merging.
- Preserve loopback-only defaults. Keep inference local by default and require explicit setup for downloads.
- Route operating-system actions through declared tools, checked targets and user authorization. Keep mutation confirmation and avoid force-closing apps.
- Run `python -m pytest -q`. Use fixtures for Ollama and Home Assistant in CI. Describe real microphone, GPU and platform checks separately.
- Preserve user profiles, files and models. Update [status](docs/STATUS.md) and [decisions](docs/DECISIONS.md) at each milestone.
- Keep the [offline demo](docs/QUICK_DEMO.md), [troubleshooting](docs/LINUX_INSTALL.md#диагностика) and [defense Q&A](docs/DEFENSE_QA.md) accurate.
