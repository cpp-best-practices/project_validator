let test_total () = Alcotest.(check int) "sums the prices" 6 (Shop.total [ 1; 2; 3 ])

let test_discounted () =
  Alcotest.(check int) "takes the percentage off" 90 (Shop.discounted ~percent:10 100);
  Alcotest.(check int) "ignores a negative percentage" 100 (Shop.discounted ~percent:(-5) 100)

let () =
  Alcotest.run "shop"
    [
      ( "prices",
        [
          Alcotest.test_case "total" `Quick test_total;
          Alcotest.test_case "discounted" `Quick test_discounted;
        ] );
    ]
