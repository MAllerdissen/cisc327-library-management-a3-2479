# tests/test_library_service_core.py
import pytest
from datetime import datetime, timedelta
from services import library_service
from services.library_service import pay_late_fees, refund_late_fee_payment
from services.payment_service import PaymentGateway

# ---------- R1: add_book_to_catalog ----------

def test_add_book_success(mocker):
    # isbn does not exist
    mocker.patch("services.library_service.get_book_by_isbn", return_value=None)
    # insert works
    mocker.patch("services.library_service.insert_book", return_value=True)

    ok, msg = library_service.add_book_to_catalog(
        "Clean Code", "Robert Martin", "1234567890123", 3
    )
    assert ok is True
    assert "successfully" in msg.lower()


def test_add_book_missing_title(mocker):
    ok, msg = library_service.add_book_to_catalog(
        "", "Some Author", "1234567890123", 1
    )
    assert ok is False
    assert "title is required" in msg.lower()


def test_add_book_duplicate_isbn(mocker):
    mocker.patch("services.library_service.get_book_by_isbn", return_value={"id": 1})
    ok, msg = library_service.add_book_to_catalog(
        "A", "B", "1234567890123", 1
    )
    assert ok is False
    assert "already exists" in msg.lower()


def test_add_book_db_error(mocker):
    mocker.patch("services.library_service.get_book_by_isbn", return_value=None)
    mocker.patch("services.library_service.insert_book", side_effect=Exception("db"))
    ok, msg = library_service.add_book_to_catalog(
        "A", "B", "1234567890123", 1
    )
    assert ok is False
    assert "database error" in msg.lower()


# ---------- R3: borrow_book_by_patron ----------

def test_borrow_book_success(mocker):
    mocker.patch("services.library_service._is_valid_patron_id", return_value=True)
    mocker.patch("services.library_service.get_book_by_id", return_value={
        "id": 10, "title": "Test Book", "available_copies": 2
    })
    mocker.patch("services.library_service.get_patron_borrow_count", return_value=0)
    mocker.patch("services.library_service.insert_borrow_record", return_value=True)
    mocker.patch("services.library_service.update_book_availability", return_value=True)

    ok, msg = library_service.borrow_book_by_patron("123456", 10)
    assert ok is True
    assert "borrowed" in msg.lower()
    assert "due date" in msg.lower()


def test_borrow_book_invalid_patron_id():
    ok, msg = library_service.borrow_book_by_patron("12", 1)
    assert ok is False
    assert "invalid patron" in msg.lower()


def test_borrow_book_not_found(mocker):
    mocker.patch("services.library_service._is_valid_patron_id", return_value=True)
    mocker.patch("services.library_service.get_book_by_id", return_value=None)
    ok, msg = library_service.borrow_book_by_patron("123456", 999)
    assert ok is False
    assert "not found" in msg.lower()


def test_borrow_book_unavailable(mocker):
    mocker.patch("services.library_service._is_valid_patron_id", return_value=True)
    mocker.patch("services.library_service.get_book_by_id", return_value={
        "id": 10, "title": "Test Book", "available_copies": 0
    })
    ok, msg = library_service.borrow_book_by_patron("123456", 10)
    assert ok is False
    assert "not available" in msg.lower()


def test_borrow_book_over_limit(mocker):
    mocker.patch("services.library_service._is_valid_patron_id", return_value=True)
    mocker.patch("services.library_service.get_book_by_id", return_value={
        "id": 10, "title": "Test Book", "available_copies": 1
    })
    mocker.patch("services.library_service.get_patron_borrow_count", return_value=5)
    ok, msg = library_service.borrow_book_by_patron("123456", 10)
    assert ok is False
    assert "maximum borrowing limit" in msg.lower()


def test_borrow_book_insert_record_fails(mocker):
    mocker.patch("services.library_service._is_valid_patron_id", return_value=True)
    mocker.patch("services.library_service.get_book_by_id", return_value={
        "id": 10, "title": "Test Book", "available_copies": 1
    })
    mocker.patch("services.library_service.get_patron_borrow_count", return_value=0)
    mocker.patch("services.library_service.insert_borrow_record", return_value=False)

    ok, msg = library_service.borrow_book_by_patron("123456", 10)
    assert ok is False
    assert "database error" in msg.lower()


def test_borrow_book_update_availability_fails(mocker):
    mocker.patch("services.library_service._is_valid_patron_id", return_value=True)
    mocker.patch("services.library_service.get_book_by_id", return_value={
        "id": 10, "title": "Test Book", "available_copies": 1
    })
    mocker.patch("services.library_service.get_patron_borrow_count", return_value=0)
    mocker.patch("services.library_service.insert_borrow_record", return_value=True)
    mocker.patch("services.library_service.update_book_availability", return_value=False)

    ok, msg = library_service.borrow_book_by_patron("123456", 10)
    assert ok is False
    assert "database error" in msg.lower()


# ---------- R4: return_book_by_patron ----------

def test_return_book_success_with_fee(mocker):
    mocker.patch("services.library_service._is_valid_patron_id", return_value=True)
    mocker.patch("services.library_service.get_book_by_id", return_value={
        "id": 10, "title": "Test Book"
    })
    mocker.patch("services.library_service.update_borrow_record_return_date", return_value=True)
    mocker.patch("services.library_service.update_book_availability", return_value=True)
    # make fee nonzero
    mocker.patch(
        "services.library_service.calculate_late_fee_for_book",
        return_value={"fee_amount": 3.5, "days_overdue": 2},
    )

    ok, msg = library_service.return_book_by_patron("123456", 10)
    assert ok is True
    assert "late fee" in msg.lower()


def test_return_book_success_no_fee(mocker):
    mocker.patch("services.library_service._is_valid_patron_id", return_value=True)
    mocker.patch("services.library_service.get_book_by_id", return_value={
        "id": 10, "title": "Test Book"
    })
    mocker.patch("services.library_service.update_borrow_record_return_date", return_value=True)
    mocker.patch("services.library_service.update_book_availability", return_value=True)
    mocker.patch(
        "services.library_service.calculate_late_fee_for_book",
        return_value={"fee_amount": 0.0, "days_overdue": 0},
    )
    ok, msg = library_service.return_book_by_patron("123456", 10)
    assert ok is True
    assert "no late fee" in msg.lower()


def test_return_book_invalid_patron():
    ok, msg = library_service.return_book_by_patron("xx", 1)
    assert ok is False
    assert "invalid patron" in msg.lower()


def test_return_book_not_found(mocker):
    mocker.patch("services.library_service._is_valid_patron_id", return_value=True)
    mocker.patch("services.library_service.get_book_by_id", return_value=None)
    ok, msg = library_service.return_book_by_patron("123456", 1)
    assert ok is False
    assert "not found" in msg.lower()


def test_return_book_update_record_fails(mocker):
    mocker.patch("services.library_service._is_valid_patron_id", return_value=True)
    mocker.patch("services.library_service.get_book_by_id", return_value={"id": 1, "title": "x"})
    mocker.patch("services.library_service.update_borrow_record_return_date", return_value=False)
    ok, msg = library_service.return_book_by_patron("123456", 1)
    assert ok is False
    assert "no active borrow record" in msg.lower()


def test_return_book_update_availability_fails(mocker):
    mocker.patch("services.library_service._is_valid_patron_id", return_value=True)
    mocker.patch("services.library_service.get_book_by_id", return_value={"id": 1, "title": "x"})
    mocker.patch("services.library_service.update_borrow_record_return_date", return_value=True)
    mocker.patch("services.library_service.update_book_availability", return_value=False)
    ok, msg = library_service.return_book_by_patron("123456", 1)
    assert ok is False
    assert "database error" in msg.lower()


# ---------- R5: late fee calculation ----------

def test_calculate_late_fee_found_overdue(mocker):
    # Borrowed 3 days ago, due 1 day ago → 1 day overdue → 0.50
    borrowed = [{
        "book_id": 10,
        "due_date": (datetime.now() - timedelta(days=1)).isoformat()
    }]
    mocker.patch("services.library_service.database.get_patron_borrowed_books", return_value=borrowed)
    result = library_service.calculate_late_fee_for_book("123456", 10)
    assert result["fee_amount"] == 0.5
    assert result["days_overdue"] == 1


def test_calculate_late_fee_not_found(mocker):
    mocker.patch("services.library_service.database.get_patron_borrowed_books", return_value=[])
    result = library_service.calculate_late_fee_for_book("123456", 99)
    assert result["fee_amount"] == 0.0
    assert result["days_overdue"] == 0


def test_calculate_late_fee_db_error_returns_zero(mocker):
    mocker.patch(
        "services.library_service.database.get_patron_borrowed_books",
        side_effect=Exception("db error"),
    )
    result = library_service.calculate_late_fee_for_book("123456", 99)
    assert result["fee_amount"] == 0.0


# ---------- search_books_in_catalog ----------

def test_search_books_empty_term_returns_empty():
    assert library_service.search_books_in_catalog("") == []


def test_search_books_title(mocker):
    mocker.patch("services.library_service.database.get_all_books", return_value=[
        {"title": "Python 101", "author": "A"},
        {"title": "Java 17", "author": "B"},
    ])
    results = library_service.search_books_in_catalog("python", "title")
    assert len(results) == 1
    assert results[0]["title"] == "Python 101"


def test_search_books_author(mocker):
    mocker.patch("services.library_service.database.get_all_books", return_value=[
        {"title": "X", "author": "Grace Hopper"},
        {"title": "Y", "author": "Other"},
    ])
    results = library_service.search_books_in_catalog("hopper", "author")
    assert len(results) == 1


def test_search_books_isbn(mocker):
    mocker.patch("services.library_service.database.get_book_by_isbn", return_value={"id": 1})
    results = library_service.search_books_in_catalog("123", "isbn")
    assert len(results) == 1


def test_search_books_invalid_type():
    results = library_service.search_books_in_catalog("term", "weird")
    assert results == []


# ---------- R7: get_patron_status_report ----------

def test_get_patron_status_report_invalid_id():
    report = library_service.get_patron_status_report("12")
    assert report["num_currently_borrowed"] == 0
    assert report["total_late_fees"] == 0.0


def test_get_patron_status_report_success(mocker):
    mocker.patch("services.library_service._is_valid_patron_id", return_value=True)

    # current borrowed list: 1 item
    mocker.patch(
        "services.library_service.database.get_patron_borrowed_books",
        return_value=[{
            "book_id": 1,
            "title": "T1",
            "borrow_date": datetime.now(),
            "due_date": datetime.now() + timedelta(days=1),
        }],
    )

    # history list (doesn't affect total_late_fees in this implementation)
    mocker.patch(
        "services.library_service.database.get_patron_borrow_history",
        return_value=[{
            "book_id": 1,
            "title": "T1",
            "borrow_date": datetime.now() - timedelta(days=10),
            "return_date": datetime.now() - timedelta(days=5),
            "late_fee": 2.0,
        }],
    )

    # IMPORTANT: the function recomputes fees for *current* loans, so we stub that
    mocker.patch(
        "services.library_service.calculate_late_fee_for_book",
        return_value={"fee_amount": 2.0, "days_overdue": 1},
    )

    report = library_service.get_patron_status_report("123456")

    assert report["num_currently_borrowed"] == 1
    assert report["total_late_fees"] == 2.0
    assert len(report["currently_borrowed"]) == 1
    assert len(report["borrowing_history"]) == 1



def test_get_patron_status_report_handles_db_errors(mocker):
    mocker.patch("services.library_service._is_valid_patron_id", return_value=True)
    mocker.patch(
        "services.library_service.database.get_patron_borrowed_books",
        side_effect=Exception("db fail"),
    )
    mocker.patch(
        "services.library_service.database.get_patron_borrow_history",
        side_effect=Exception("db fail"),
    )
    report = library_service.get_patron_status_report("123456")
    assert report["num_currently_borrowed"] == 0
    assert report["total_late_fees"] == 0.0
