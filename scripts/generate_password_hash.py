#!/usr/bin/env python3
"""
DocHopper Password Hash Generator

This script generates SHA-256 password hashes with salt for the auth_users.json file.
Run this script to create new user credentials.

Usage:
    python generate_password_hash.py

The script will prompt for a password and output the hash and salt to add to auth_users.json.
"""

import hashlib
import secrets
import getpass
import json


def generate_password_hash(password: str) -> dict:
    """Generate a salted SHA-256 hash for a password.

    Returns dict with 'password_hash' and 'salt' to add to auth_users.json
    """
    salt = secrets.token_hex(16)
    salted = f"{salt}{password}".encode('utf-8')
    password_hash = hashlib.sha256(salted).hexdigest()

    return {
        'password_hash': password_hash,
        'salt': salt
    }


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Verify a password against stored hash and salt."""
    salted = f"{salt}{password}".encode('utf-8')
    computed_hash = hashlib.sha256(salted).hexdigest()
    return computed_hash == stored_hash


def main():
    print("=" * 60)
    print("DocHopper Password Hash Generator")
    print("=" * 60)
    print()

    # Get user email
    email = input("Enter user email: ").strip()
    if not email:
        print("Error: Email is required")
        return

    # Get user name
    name = input("Enter user display name: ").strip() or email

    # Get role
    role = input("Enter role (admin/user) [user]: ").strip().lower() or "user"
    if role not in ("admin", "user"):
        print(f"Warning: Unknown role '{role}', using 'user'")
        role = "user"

    # Get password (hidden input)
    print()
    password = getpass.getpass("Enter password: ")
    if not password:
        print("Error: Password is required")
        return

    password_confirm = getpass.getpass("Confirm password: ")
    if password != password_confirm:
        print("Error: Passwords do not match")
        return

    # Generate hash
    result = generate_password_hash(password)

    # Verify it works
    if not verify_password(password, result['password_hash'], result['salt']):
        print("Error: Hash verification failed!")
        return

    print()
    print("=" * 60)
    print("SUCCESS! Add this entry to auth_users.json:")
    print("=" * 60)
    print()

    user_entry = {
        email: {
            "password_hash": result['password_hash'],
            "salt": result['salt'],
            "role": role,
            "name": name
        }
    }

    print(json.dumps(user_entry, indent=4))

    print()
    print("=" * 60)
    print("Copy the above JSON and merge it into the 'users' object")
    print("in your auth_users.json file.")
    print("=" * 60)


if __name__ == "__main__":
    main()
