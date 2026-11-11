using Shop
using Test
using Aqua
using JET

@testset "Shop" begin
    @testset "quality" begin
        Aqua.test_all(Shop)
        JET.test_package(Shop; target_defined_modules = true)
    end
    @testset "total" begin
        @test total([1, 2, 3]) == 6
        @test total(Int[]) == 0
    end
    @testset "discounted" begin
        @test discounted(100, 10) == 90
        @test discounted(100, -5) == 100
    end
end
