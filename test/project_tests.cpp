#include "temp_project.hpp"

#include <catch2/catch_test_macros.hpp>

#include <algorithm>
#include <filesystem>
#include <string>
#include <vector>

namespace {
[[nodiscard]] std::vector<std::string> generic_strings(const std::vector<std::filesystem::path> &paths)
{
  std::vector<std::string> result;
  std::ranges::transform(paths, std::back_inserter(result), [](const auto &path) { return path.generic_string(); });
  return result;
}
}// namespace

TEST_CASE("Project reports file existence relative to its root")
{
  project_validator::test::Temp_Project temp;
  temp.write("CMakeLists.txt", "project(test)");
  const auto project = temp.project();

  CHECK(project.exists("CMakeLists.txt"));
  CHECK_FALSE(project.exists("missing.txt"));
}

TEST_CASE("Project reads file contents")
{
  project_validator::test::Temp_Project temp;
  temp.write("a/b.txt", "hello");
  const auto project = temp.project();

  CHECK(project.read_file("a/b.txt") == "hello");
  CHECK_FALSE(project.read_file("a/missing.txt").has_value());
  CHECK_FALSE(project.read_file("a").has_value());
}

TEST_CASE("Project lists regular files of a directory in sorted order")
{
  project_validator::test::Temp_Project temp;
  temp.write("dir/z.yml", "").write("dir/a.yml", "").make_directory("dir/sub");
  const auto project = temp.project();

  CHECK(generic_strings(project.files_in("dir")) == std::vector<std::string>{ "dir/a.yml", "dir/z.yml" });
  CHECK(project.files_in("missing").empty());
}

TEST_CASE("Project finds CMake files while skipping hidden directories and build trees")
{
  project_validator::test::Temp_Project temp;
  temp.write("CMakeLists.txt", "")
    .write("cmake/Coverage.cmake", "")
    .write("src/CMakeLists.txt", "")
    .write("src/main.cpp", "")
    .write(".git/CMakeLists.txt", "")
    .write("build/CMakeCache.txt", "")
    .write("build/_deps/catch2-src/CMakeLists.txt", "");
  const auto project = temp.project();

  CHECK(generic_strings(project.cmake_files())
        == std::vector<std::string>{ "CMakeLists.txt", "cmake/Coverage.cmake", "src/CMakeLists.txt" });
}
