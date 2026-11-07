program check
   use app, only: add
   implicit none
   if (add(1, 2) /= 3) error stop "1 + 2 /= 3"
end program check
