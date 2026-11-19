#include <stddef.h>
#include <stdint.h>

/* A libFuzzer target: the fuzzer calls it with generated inputs. */
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
  return (data != NULL && size > 0) ? 0 : 0;
}
