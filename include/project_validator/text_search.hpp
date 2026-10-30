#ifndef PROJECT_VALIDATOR_TEXT_SEARCH_HPP
#define PROJECT_VALIDATOR_TEXT_SEARCH_HPP

#include <project_validator/project.hpp>

#include <filesystem>
#include <regex>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace project_validator {

// A named, case-insensitive regular expression used to recognise project features in text.
struct Pattern
{
  Pattern(std::string pattern_name, std::string_view expression);

  std::string name;
  std::regex regex;
};

[[nodiscard]] bool matches(std::string_view text, const Pattern &pattern);
[[nodiscard]] bool any_matches(std::span<const std::string> texts, const Pattern &pattern);
[[nodiscard]] bool any_matches(std::span<const std::string> texts, std::span<const Pattern> patterns);
[[nodiscard]] std::vector<std::string> matching_names(std::span<const std::string> texts, std::span<const Pattern> patterns);

[[nodiscard]] std::vector<std::string> read_files(const Project &project, std::span<const std::filesystem::path> files);
[[nodiscard]] std::string join(std::span<const std::string> values, std::string_view separator);

}// namespace project_validator

#endif
