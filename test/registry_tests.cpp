#include "temp_project.hpp"

#include <project_validator/registry.hpp>

#include <catch2/catch_test_macros.hpp>

#include <memory>
#include <stdexcept>
#include <string>
#include <string_view>

namespace {
class Fixed_Check final : public project_validator::Check
{
public:
  Fixed_Check(std::string name, const project_validator::Status status) : m_name{ std::move(name) }, m_status{ status } {}

  [[nodiscard]] std::string_view name() const noexcept override { return m_name; }
  [[nodiscard]] project_validator::Check_Result run(const project_validator::Project & /*project*/) const override
  {
    return { m_status, m_name + " ran" };
  }

private:
  std::string m_name;
  project_validator::Status m_status;
};
}// namespace

TEST_CASE("Registry runs every registered check in registration order")
{
  project_validator::Registry registry;
  registry.add(std::make_unique<Fixed_Check>("first", project_validator::Status::pass));
  registry.emplace<Fixed_Check>("second", project_validator::Status::fail);

  REQUIRE(registry.size() == 2);

  const project_validator::test::Temp_Project temp;
  const auto reports = registry.run_all(temp.project());

  REQUIRE(reports.size() == 2);
  CHECK(reports[0].name == "first");
  CHECK(reports[0].result.status == project_validator::Status::pass);
  CHECK(reports[0].result.message == "first ran");
  CHECK(reports[1].name == "second");
  CHECK(reports[1].result.status == project_validator::Status::fail);
  CHECK_FALSE(project_validator::all_passed(reports));
}

TEST_CASE("all_passed is true only when no check failed")
{
  project_validator::Registry registry;
  registry.emplace<Fixed_Check>("only", project_validator::Status::pass);

  const project_validator::test::Temp_Project temp;
  CHECK(project_validator::all_passed(registry.run_all(temp.project())));
}

TEST_CASE("Registry rejects null checks")
{
  project_validator::Registry registry;
  CHECK_THROWS_AS(registry.add(nullptr), std::invalid_argument);
}

TEST_CASE("Status converts to a printable name")
{
  STATIC_CHECK(project_validator::to_string(project_validator::Status::pass) == "PASS");
  STATIC_CHECK(project_validator::to_string(project_validator::Status::fail) == "FAIL");
}
