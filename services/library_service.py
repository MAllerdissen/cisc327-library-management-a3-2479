"""
services/library_service.py
Library Service Module - Business Logic Functions
Contains all the core business logic for the Library Management System
"""

from datetime import datetime, timedelta
from typing import Dict, Optional, List, Tuple, Any
import database  # keep module ref so tests can monkeypatch database.*
from database import (
    get_book_by_id, get_book_by_isbn, get_patron_borrow_count,
    insert_borrow_record, update_book_availability,
    update_borrow_record_return_date,
)
from services.payment_service import PaymentGateway

MAX_BORROW_LIMIT = 5
BORROW_DAYS = 14


def _is_valid_isbn13(isbn: str) -> bool:
    return isbn.isdigit() and len(isbn) == 13


def _is_valid_patron_id(pid: str) -> bool:
    return pid.isdigit() and len(pid) == 6


def insert_book(title: str, author: str, isbn: str, total_copies: int, available_copies: int):
    # Ignore available_copies here; DB layer computes availability internally.
    return database.insert_book(title, author, isbn, total_copies)


# ---------------- R1 ----------------

def add_book_to_catalog(title: str, author: str, isbn: str, total_copies: int) -> Tuple[bool, str]:
    """
    Validation/messages follow the test expectations exactly.
    On success, calls insert_book(title, author, isbn, total, available) with available == total.
    """
    title = (title or '').strip()
    author = (author or '').strip()
    isbn = (isbn or '').strip()

    if not title:
        return False, "Title is required."
    if len(title) > 200:
        return False, "Title must be less than 200 characters."
    if not author:
        return False, "Author is required."
    if len(author) > 100:
        return False, "Author must be less than 100 characters."
    if not _is_valid_isbn13(isbn):
        return False, "ISBN must be exactly 13 digits."
    if not isinstance(total_copies, int) or total_copies <= 0:
        return False, "Total copies must be a positive integer."
    if get_book_by_isbn(isbn) is not None:
        return False, "A book with this ISBN already exists."

    try:
        ok = insert_book(title, author, isbn, total_copies, total_copies)  # tests patch THIS symbol
    except Exception:
        return False, "Database error occurred while adding the book."
    if not ok:
        return False, "Database error occurred while adding the book."

    return True, f'Book "{title}" successfully added to catalog.'


# ---------------- R3 ----------------

def borrow_book_by_patron(patron_id: str, book_id: int) -> Tuple[bool, str]:
    """
    Borrow a book for a patron (R3). Messages match the tests.
    """
    if not _is_valid_patron_id(patron_id):
        return False, "Invalid patron ID. Must be exactly 6 digits."

    book = get_book_by_id(book_id)
    if not book:
        return False, "Book not found."
    if int(book["available_copies"]) <= 0:
        return False, "This book is currently not available."
    if get_patron_borrow_count(patron_id) >= MAX_BORROW_LIMIT:
        return False, "You have reached the maximum borrowing limit of 5 books."

    borrow_date = datetime.now()
    due_date = borrow_date + timedelta(days=BORROW_DAYS)

    if not insert_borrow_record(patron_id, book_id, borrow_date, due_date):
        return False, "Database error occurred while creating borrow record."
    if not update_book_availability(book_id, -1):
        return False, "Database error occurred while updating book availability."

    return True, f'Borrowed "{book["title"]}" successfully. Due date: {due_date.strftime("%Y-%m-%d")}.'


# ---------------- R4 ----------------

def return_book_by_patron(patron_id: str, book_id: int) -> Tuple[bool, str]:
    """
    Return flow and messages match tests exactly.
    """
    if not _is_valid_patron_id(patron_id):
        return False, "Invalid patron ID. Must be exactly 6 digits."

    book = get_book_by_id(book_id)
    if not book:
        return False, "Book not found."

    return_dt = datetime.now()
    if not update_borrow_record_return_date(patron_id, book_id, return_dt):
        return False, "No active borrow record found for this patron and book."

    if not update_book_availability(book_id, +1):
        return False, "Database error occurred while updating book availability."

    fee_data = calculate_late_fee_for_book(patron_id, book_id)
    fee_amount = float(fee_data.get('fee_amount', 0.0))
    if fee_amount > 0:
        return True, f'Return processed for "{book["title"]}". Late fee: ${fee_amount:.2f}.'
    else:
        return True, f'Return processed for "{book["title"]}". No late fee.'


# ---------------- R5 (late fee calculation) ----------------

def _compute_fee(days_overdue: int) -> float:
    if days_overdue <= 0:
        return 0.0
    first = min(days_overdue, 7) * 0.50
    rest = max(0, days_overdue - 7) * 1.00
    total = first + rest
    return round(15.0 if total > 15.0 else total, 2)


def calculate_late_fee_for_book(patron_id: str, book_id: int) -> Dict[str, Any]:
    """
    Returns {'fee_amount': float, 'days_overdue': int}.
    Uses database.get_patron_borrowed_books(monkeypatched in tests).
    """
    try:
        borrowed = database.get_patron_borrowed_books(patron_id)
    except Exception:
        borrowed = []

    match = None
    for r in borrowed:
        try:
            if int(r.get('book_id')) == int(book_id):
                match = r
                break
        except Exception:
            continue

    if not match:
        return {'fee_amount': 0.0, 'days_overdue': 0}

    due = match.get('due_date')
    if isinstance(due, str):
        try:
            due_dt = datetime.fromisoformat(due)
        except Exception:
            return {'fee_amount': 0.0, 'days_overdue': 0}
    else:
        due_dt = due

    days_overdue = (datetime.now().date() - due_dt.date()).days
    if days_overdue < 0:
        days_overdue = 0
    return {'fee_amount': _compute_fee(days_overdue), 'days_overdue': int(days_overdue)}


# ---------------- R6 ----------------

def search_books_in_catalog(search_term: str, search_type: str = 'title'):
    """
    Title/Author: partial, case-insensitive over database.get_all_books().
    ISBN: exact via database.get_book_by_isbn().
    Invalid type: [].
    """
    term = (search_term or '').strip()
    stype = (search_type or 'title').lower()
    if not term:
        return []

    if stype == 'title':
        books = list(database.get_all_books())  # tests patch `database.get_all_books`
        t = term.lower()
        return [b for b in books if t in str(b.get('title', '')).lower()]

    if stype == 'author':
        books = list(database.get_all_books())
        t = term.lower()
        return [b for b in books if t in str(b.get('author', '')).lower()]

    if stype == 'isbn':
        book = database.get_book_by_isbn(term)
        return [book] if book else []

    return []


# ---------------- R7 ----------------

def get_patron_status_report(patron_id: str) -> Dict[str, Any]:
    """
    Shape must be:
      'currently_borrowed', 'borrowing_history', 'num_currently_borrowed', 'total_late_fees'
    """
    if not _is_valid_patron_id(patron_id):
        return {
            'currently_borrowed': [],
            'borrowing_history': [],
            'num_currently_borrowed': 0,
            'total_late_fees': 0.0
        }

    try:
        current = database.get_patron_borrowed_books(patron_id)
    except Exception:
        current = []
    try:
        history = database.get_patron_borrow_history(patron_id)
    except Exception:
        history = []

    def _as_iso(d):
        if isinstance(d, datetime):
            return d.isoformat()
        return str(d) if d is not None else None

    cur_list: List[Dict[str, Any]] = []
    total_fees = 0.0
    for r in current:
        bid = r.get('book_id')
        fee_info = calculate_late_fee_for_book(patron_id, bid)
        total_fees += float(fee_info.get('fee_amount', 0.0))
        cur_list.append({
            'book_id': bid,
            'title': r.get('title'),
            'due_date': _as_iso(r.get('due_date')),
        })

    hist_list: List[Dict[str, Any]] = []
    for r in history:
        hist_list.append({
            'book_id': r.get('book_id'),
            'title': r.get('title'),
            'borrow_date': _as_iso(r.get('borrow_date')),
            'return_date': _as_iso(r.get('return_date')),
        })

    return {
        'currently_borrowed': cur_list,
        'borrowing_history': hist_list,
        'num_currently_borrowed': len(cur_list),
        'total_late_fees': round(total_fees, 2)
    }


def pay_late_fees(patron_id: str, book_id: int, payment_gateway: PaymentGateway = None) -> Tuple[bool, str, Optional[str]]:
    """
    Process payment for late fees using external payment gateway.
    
    NEW FEATURE FOR ASSIGNMENT 3: Demonstrates need for mocking/stubbing
    This function depends on an external payment service that should be mocked in tests.
    
    Args:
        patron_id: 6-digit library card ID
        book_id: ID of the book with late fees
        payment_gateway: Payment gateway instance (injectable for testing)
        
    Returns:
        tuple: (success: bool, message: str, transaction_id: Optional[str])
        
    Example for you to mock:
        # In tests, mock the payment gateway:
        mock_gateway = Mock(spec=PaymentGateway)
        mock_gateway.process_payment.return_value = (True, "txn_123", "Success")
        success, msg, txn = pay_late_fees("123456", 1, mock_gateway)
    """
    # Validate patron ID
    if not patron_id or not patron_id.isdigit() or len(patron_id) != 6:
        return False, "Invalid patron ID. Must be exactly 6 digits.", None
    
    # Calculate late fee first
    fee_info = calculate_late_fee_for_book(patron_id, book_id)
    
    # Check if there's a fee to pay
    if not fee_info or 'fee_amount' not in fee_info:
        return False, "Unable to calculate late fees.", None
    
    fee_amount = fee_info.get('fee_amount', 0.0)
    
    if fee_amount <= 0:
        return False, "No late fees to pay for this book.", None
    
    # Get book details for payment description
    book = get_book_by_id(book_id)
    if not book:
        return False, "Book not found.", None
    
    # Use provided gateway or create new one
    if payment_gateway is None:
        payment_gateway = PaymentGateway()
    
    # Process payment through external gateway
    # THIS IS WHAT YOU SHOULD MOCK IN THEIR TESTS!
    try:
        success, transaction_id, message = payment_gateway.process_payment(
            patron_id=patron_id,
            amount=fee_amount,
            description=f"Late fees for '{book['title']}'"
        )
        
        if success:
            return True, f"Payment successful! {message}", transaction_id
        else:
            return False, f"Payment failed: {message}", None
            
    except Exception as e:
        # Handle payment gateway errors
        return False, f"Payment processing error: {str(e)}", None


def refund_late_fee_payment(transaction_id: str, amount: float, payment_gateway: PaymentGateway = None) -> Tuple[bool, str]:
    """
    Refund a late fee payment (e.g., if book was returned on time but fees were charged in error).
    
    NEW FEATURE FOR ASSIGNMENT 3: Another function requiring mocking
    
    Args:
        transaction_id: Original transaction ID to refund
        amount: Amount to refund
        payment_gateway: Payment gateway instance (injectable for testing)
        
    Returns:
        tuple: (success: bool, message: str)
    """
    # Validate inputs
    if not transaction_id or not transaction_id.startswith("txn_"):
        return False, "Invalid transaction ID."
    
    if amount <= 0:
        return False, "Refund amount must be greater than 0."
    
    if amount > 15.00:  # Maximum late fee per book
        return False, "Refund amount exceeds maximum late fee."
    
    # Use provided gateway or create new one
    if payment_gateway is None:
        payment_gateway = PaymentGateway()
    
    # Process refund through external gateway
    # THIS IS WHAT YOU SHOULD MOCK IN YOUR TESTS!
    try:
        success, message = payment_gateway.refund_payment(transaction_id, amount)
        
        if success:
            return True, message
        else:
            return False, f"Refund failed: {message}"
            
    except Exception as e:
        return False, f"Refund processing error: {str(e)}"