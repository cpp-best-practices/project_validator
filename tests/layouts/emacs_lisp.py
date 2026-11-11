"""Kinds of Emacs Lisp project, for tests that run a check in every layout."""

from tests.layouts.model import ProjectLayout

SOURCE = (
    ";;; shop.el --- Prices of the shop's items  -*- lexical-binding: t; -*-\n\n"
    '(defun shop-total (prices)\n  "The sum of PRICES."\n  (apply #\'+ prices))\n\n'
    "(provide 'shop)\n;;; shop.el ends here\n"
)

LAYOUTS = (
    ProjectLayout(
        name="Eask package",
        files={
            "Eask": '(package "shop" "0.1.0" "Prices of the shop\'s items")\n(package-file "shop.el")\n',
            "shop.el": SOURCE,
        },
        languages=frozenset({"Emacs Lisp"}),
        build_systems=frozenset({"Eask"}),
    ),
    ProjectLayout(
        name="Emacs Lisp sources",
        files={"lisp/shop.el": SOURCE},
        languages=frozenset({"Emacs Lisp"}),
        build_systems=frozenset(),
    ),
)
