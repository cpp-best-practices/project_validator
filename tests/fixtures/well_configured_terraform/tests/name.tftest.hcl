run "generates_a_name" {
  command = plan

  assert {
    condition     = var.words == 2
    error_message = "two words by default"
  }
}
