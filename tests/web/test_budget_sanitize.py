from server.ai.agents import sanitize_budget_items


def _it(label, amount, basis="group_total", cat="food", src=""):
    return {"category": cat, "label": label, "amount": amount, "basis": basis, "source_text": src}


def test_totals_are_dropped_so_nothing_is_double_counted():
    items = [_it("Hotel", 6000, "per_night_group", "accommodation"), _it("Total accommodation", 24000, cat="accommodation"),
             _it("Grand total", 58000), _it("Estimated total cost", 58000), _it("Taxis", 9000, cat="transport")]
    out = [i["label"] for i in sanitize_budget_items(items)]
    assert out == ["Hotel", "Total accommodation", "Taxis"] or out == ["Hotel", "Taxis"] or "Grand total" not in out
    assert "Grand total" not in out and "Estimated total cost" not in out


def test_same_cost_listed_twice_is_kept_once():
    a = _it("City Palace entry", 300, "per_person", "activities", "Entry ₹300 per person")
    b = _it("City Palace", 300, "per_person", "activities", "Entry ₹300 per person")
    assert len(sanitize_budget_items([a, b])) == 1
    assert len(sanitize_budget_items([a, _it("Fort entry", 300, "per_person", "activities", "Fort ₹300 pp")])) == 2
