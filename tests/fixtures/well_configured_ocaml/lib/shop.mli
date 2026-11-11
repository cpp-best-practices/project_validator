(** Prices of the shop's items. *)

val total : int list -> int
(** The sum of [prices]. *)

val discounted : percent:int -> int -> int
(** [price] with [percent] taken off; a percentage of zero or less changes nothing. *)
