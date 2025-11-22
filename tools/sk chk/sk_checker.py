"""
Stripe SK Key Checker Tool
Validates and checks Stripe secret keys by querying the balance API
"""

import re
import requests
import base64
from typing import Dict, Any


def validate_sk_format(sk_key: str) -> bool:
    """
    Validate if the SK key has the correct format
    
    Args:
        sk_key: The SK key to validate
    
    Returns:
        True if valid format, False otherwise
    """
    pattern = r'sk_(test|live)_[A-Za-z0-9]+'
    return bool(re.match(pattern, sk_key))


def mask_sk_key(sk_key: str) -> str:
    """
    Mask the SK key for display (show first 12 chars and last 4 chars)
    
    Args:
        sk_key: The full SK key
    
    Returns:
        Masked SK key
    """
    if len(sk_key) > 16:
        return f"{sk_key[:12]}_SWDQYL_{sk_key[-4:]}"
    return sk_key


def check_stripe_sk(sk_key: str) -> Dict[str, Any]:
    """
    Check Stripe SK key by querying the balance API
    
    Args:
        sk_key: The Stripe secret key to check
    
    Returns:
        Dict containing check results or error information
    """
    try:
        # Validate format first
        if not validate_sk_format(sk_key):
            return {
                'success': False,
                'error': 'Enter Valid SK Key'
            }
        
        # Prepare authorization header (Basic auth with SK key)
        auth_string = base64.b64encode(sk_key.encode()).decode()
        headers = {
            'Authorization': f'Basic {auth_string}'
        }
        
        # Query Stripe balance API
        response = requests.get(
            'https://api.stripe.com/v1/balance',
            headers=headers,
            timeout=15
        )
        
        # Check if request was successful
        if response.status_code != 200:
            try:
                error_data = response.json()
                error_message = error_data.get('error', {}).get('message', "This SK Key isn't Valid")
                return {
                    'success': False,
                    'error': error_message
                }
            except:
                return {
                    'success': False,
                    'error': "This SK Key isn't Valid"
                }
        
        # Parse response
        data = response.json()
        
        # Check if there's an error in the response
        if 'error' in data:
            error_message = data['error'].get('message', "This SK Key isn't Valid")
            return {
                'success': False,
                'error': error_message
            }
        
        # Extract balance information
        available = data.get('available', [{}])[0]
        pending = data.get('pending', [{}])[0]
        
        currency = available.get('currency', 'N/A').upper()
        available_amount = available.get('amount', 0)
        pending_amount = pending.get('amount', 0)
        
        # Convert amounts from cents to dollars (divide by 100)
        available_display = available_amount / 100 if available_amount else 0
        pending_display = pending_amount / 100 if pending_amount else 0
        
        result = {
            'success': True,
            'data': {
                'sk_key': sk_key,
                'masked_sk': mask_sk_key(sk_key),
                'currency': currency,
                'available': available_display,
                'pending': pending_display,
                'available_raw': available_amount,
                'pending_raw': pending_amount
            }
        }
        
        return result
        
    except requests.exceptions.Timeout:
        return {
            'success': False,
            'error': 'Request timed out'
        }
    except requests.exceptions.RequestException as e:
        return {
            'success': False,
            'error': f'Network error: {str(e)}'
        }
    except Exception as e:
        return {
            'success': False,
            'error': f'Unexpected error: {str(e)}'
        }


def format_sk_check_message(result: Dict[str, Any]) -> str:
    """
    Format the SK check result into a Telegram message
    
    Args:
        result: Result from check_stripe_sk()
    
    Returns:
        Formatted message string
    """
    if not result.get('success'):
        return f"[❌] <b>Error</b> → <i>{result.get('error', 'Unknown error')}</i>!"
    
    data = result['data']
    
    message = (
        f"[🔑] <b>SK Key</b> ↯ <code>{data['masked_sk']}</code>\n\n"
        f"[📜️] <b>Currency</b> ↯ <i>{data['currency']}</i>\n"
        f"[🏦] <b>Balance (Available - Pending)</b> ↯ "
        f"<code>{data['available']:.2f}</code> - <code>{data['pending']:.2f}</code>"
    )
    
    return message
