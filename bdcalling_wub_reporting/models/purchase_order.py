# -*- coding: utf-8 -*-
from odoo import models, fields, api


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # New Fields
    subject = fields.Char(
        string='Subject',
        help='Subject of the work order'
    )
    
    work_order_date = fields.Date(
        string='Work Order Date',
        default=fields.Date.context_today,
        help='Date of the work order'
    )
    
    # Terms & Conditions Fields
    term_payment = fields.Text(
        string='Payment Conditions',
        help='Payment terms and conditions'
    )
    
    term_delivery = fields.Text(
        string='Delivery Terms',
        help='Delivery terms and conditions'
    )
    
    term_quality_quantity = fields.Text(
        string='Quality and Quantity',
        help='Quality and quantity requirements'
    )
    
    term_penalty = fields.Text(
        string='Penalty',
        help='Penalty terms'
    )
    
    term_note = fields.Html(
        string='Note',
        help='Additional notes with formatting support',
        sanitize=True,
        sanitize_tags=True,
        sanitize_attributes=True,
        sanitize_style=True,
        strip_style=False,
        strip_classes=False
    )
    
    # Calculation Fields
    vat_percentage_add = fields.Float(
        string='VAT % (Add)',
        default=15.0,
        help='VAT percentage to add'
    )
    
    vat_percentage_less = fields.Float(
        string='VAT % (Less)',
        default=15.0,
        help='VAT percentage to deduct'
    )
    
    ait_percentage = fields.Float(
        string='AIT %',
        default=5.0,
        help='AIT percentage to deduct'
    )
    
    base_amount = fields.Monetary(
        string='Base Amount',
        compute='_compute_custom_amounts',
        store=True,
        currency_field='currency_id'
    )
    
    total_amount = fields.Monetary(
        string='Total Amount',
        compute='_compute_custom_amounts',
        store=True,
        currency_field='currency_id'
    )
    
    vat_add_amount = fields.Monetary(
        string='Add: VAT Amount',
        compute='_compute_custom_amounts',
        store=True,
        currency_field='currency_id'
    )
    
    vat_add_amount_manual = fields.Monetary(
        string='Add: VAT Amount (Manual)',
        currency_field='currency_id',
        help='Manually editable VAT add amount'
    )
    
    sub_total_amount = fields.Monetary(
        string='Sub Total',
        compute='_compute_custom_amounts',
        store=True,
        currency_field='currency_id'
    )
    
    vat_less_amount = fields.Monetary(
        string='Less: VAT Amount',
        compute='_compute_custom_amounts',
        store=True,
        currency_field='currency_id'
    )
    
    vat_less_amount_manual = fields.Monetary(
        string='Less: VAT Amount (Manual)',
        currency_field='currency_id',
        help='Manually editable VAT less amount'
    )
    
    ait_amount = fields.Monetary(
        string='Less: AIT Amount',
        compute='_compute_custom_amounts',
        store=True,
        currency_field='currency_id'
    )
    
    ait_amount_manual = fields.Monetary(
        string='Less: AIT Amount (Manual)',
        currency_field='currency_id',
        help='Manually editable AIT amount'
    )
    
    net_payable_amount = fields.Monetary(
        string='Net Payable Amount',
        compute='_compute_custom_amounts',
        store=True,
        currency_field='currency_id'
    )
    
    net_payable_amount_words = fields.Char(
        string='Net Payable Amount in Words',
        compute='_compute_amount_in_words',
        store=True
    )
    
    use_manual_calculations = fields.Boolean(
        string='Use Manual Calculations',
        default=False,
        help='Enable to manually edit calculated amounts'
    )

    def _number_to_words(self, number):
        """Convert number to words in English (without Taka/Paisa)"""
        ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine']
        teens = ['Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 
                 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen']
        tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']
        
        def convert_below_thousand(n):
            if n == 0:
                return ''
            elif n < 10:
                return ones[n]
            elif n < 20:
                return teens[n - 10]
            elif n < 100:
                return tens[n // 10] + (' ' + ones[n % 10] if n % 10 != 0 else '')
            else:
                return ones[n // 100] + ' Hundred' + (' ' + convert_below_thousand(n % 100) if n % 100 != 0 else '')
        
        if number == 0:
            return 'Zero Only'
        
        # Split into integer and decimal parts
        integer_part = int(number)
        decimal_part = round((number - integer_part) * 100)
        
        # Convert integer part
        result = ''
        
        if integer_part >= 10000000:  # Crore
            crore = integer_part // 10000000
            result += convert_below_thousand(crore) + ' Crore '
            integer_part %= 10000000
        
        if integer_part >= 100000:  # Lakh
            lakh = integer_part // 100000
            result += convert_below_thousand(lakh) + ' Lakh '
            integer_part %= 100000
        
        if integer_part >= 1000:  # Thousand
            thousand = integer_part // 1000
            result += convert_below_thousand(thousand) + ' Thousand '
            integer_part %= 1000
        
        if integer_part > 0:
            result += convert_below_thousand(integer_part)
        
        result = result.strip()
        
        # Add decimal part if exists (without "Paisa")
        if decimal_part > 0:
            result += ' Point ' + convert_below_thousand(decimal_part)
        
        return result + ' Only'

    @api.depends('net_payable_amount')
    def _compute_amount_in_words(self):
        """Convert net payable amount to words (without Taka prefix)"""
        for order in self:
            if order.net_payable_amount:
                order.net_payable_amount_words = self._number_to_words(order.net_payable_amount)
            else:
                order.net_payable_amount_words = 'Zero Only'

    @api.depends(
        'order_line.price_subtotal',
        'vat_percentage_add',
        'vat_percentage_less',
        'ait_percentage',
        'use_manual_calculations',
        'vat_add_amount_manual',
        'vat_less_amount_manual',
        'ait_amount_manual'
    )
    def _compute_custom_amounts(self):
        for order in self:
            # Calculate base amount (sum of all order lines)
            base = sum(order.order_line.mapped('price_subtotal'))
            order.base_amount = base
            order.total_amount = base
            
            if order.use_manual_calculations:
                # Use manual amounts
                order.vat_add_amount = order.vat_add_amount_manual
                order.vat_less_amount = order.vat_less_amount_manual
                order.ait_amount = order.ait_amount_manual
            else:
                # Calculate VAT Add
                order.vat_add_amount = base * (order.vat_percentage_add / 100.0)
                order.vat_add_amount_manual = order.vat_add_amount
                
                # Calculate VAT Less
                order.vat_less_amount = base * (order.vat_percentage_less / 100.0)
                order.vat_less_amount_manual = order.vat_less_amount
                
                # Calculate AIT
                order.ait_amount = base * (order.ait_percentage / 100.0)
                order.ait_amount_manual = order.ait_amount
            
            # Calculate Sub Total
            order.sub_total_amount = base + order.vat_add_amount
            
            # Calculate Net Payable Amount
            order.net_payable_amount = (
                order.sub_total_amount 
                - order.vat_less_amount 
                - order.ait_amount
            )


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'
    
    pass