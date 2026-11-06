require "app"

RSpec.describe App do
  it "adds" do
    expect(App.add(1, 2)).to eq(3)
  end
end
