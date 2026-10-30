#include "temp_project.hpp"

#include <project_validator/checks/has_ci_check.hpp>

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include <memory>
#include <vector>

using Catch::Matchers::ContainsSubstring;
using project_validator::Status;

TEST_CASE("Default CI providers detect GitHub Actions workflows")
{
  project_validator::test::Temp_Project temp;
  temp.write(".github/workflows/ci.yml", "on: push").write(".github/workflows/notes.md", "");

  const auto providers = project_validator::default_ci_providers();
  const auto files = project_validator::find_ci_files(temp.project(), providers);

  REQUIRE(files.size() == 1);
  CHECK(files[0].provider == "GitHub Actions");
  CHECK(files[0].path.generic_string() == ".github/workflows/ci.yml");
}

TEST_CASE("Default CI providers detect several CI systems")
{
  project_validator::test::Temp_Project temp;
  temp.write(".gitlab-ci.yml", "")
    .write("azure-pipelines.yml", "")
    .write(".circleci/config.yml", "")
    .write("appveyor.yml", "")
    .write(".github/workflows/build.yaml", "");

  const auto check = project_validator::Has_CI_Check{};
  const auto result = check.run(temp.project());

  CHECK(result.status == Status::pass);
  CHECK_THAT(result.message, ContainsSubstring("GitHub Actions"));
  CHECK_THAT(result.message, ContainsSubstring("GitLab CI"));
  CHECK_THAT(result.message, ContainsSubstring("Azure Pipelines"));
  CHECK_THAT(result.message, ContainsSubstring("CircleCI"));
  CHECK_THAT(result.message, ContainsSubstring("AppVeyor"));
}

TEST_CASE("Has_CI_Check fails when no CI configuration exists")
{
  project_validator::test::Temp_Project temp;
  temp.write("CMakeLists.txt", "").make_directory(".github/workflows");

  const auto result = project_validator::Has_CI_Check{}.run(temp.project());

  CHECK(result.status == Status::fail);
  CHECK_THAT(result.message, ContainsSubstring("no CI configuration"));
}

TEST_CASE("Has_CI_Check accepts custom CI providers")
{
  project_validator::test::Temp_Project temp;
  temp.write("ci/buildkite.yml", "");

  std::vector<std::unique_ptr<const project_validator::CI_Provider>> providers;
  providers.push_back(std::make_unique<const project_validator::File_Pattern_CI_Provider>(
    "Buildkite", std::vector<std::filesystem::path>{}, std::vector{ project_validator::Directory_Pattern{ "ci", { ".yml" } } }));

  const auto custom = project_validator::Has_CI_Check{ std::move(providers) };
  CHECK(custom.run(temp.project()).status == Status::pass);

  CHECK(project_validator::Has_CI_Check{}.run(temp.project()).status == Status::fail);
}
