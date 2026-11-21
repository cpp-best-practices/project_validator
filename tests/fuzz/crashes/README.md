# Crash inputs

Each folder holds the minimised inputs of fuzz crashes that have been fixed, one folder per target in `tests/fuzz/`.
`tests/test_fuzz_targets.py` replays them, with the seeds in `tests/fuzz/corpus/`, on every OS the unit tests run on,
so each fix stays a regression test.

To keep a crash:

1. Download the `fuzz-crashes-<target>` artifact of the failing `fuzzing` job (or reproduce the crash locally with
   `python tests/fuzz/fuzz_<target>.py <crash file>`).
2. Minimise it: `python tests/fuzz/fuzz_<target>.py -minimize_crash=1 -runs=10000 <crash file>`.
3. Copy the minimised file into `tests/fuzz/crashes/<target>/`, named for what it exercises
   (`unterminated-bracket-argument`), and check that the replay test fails before the fix and passes after it.
