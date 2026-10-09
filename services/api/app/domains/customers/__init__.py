"""Customers — the clients whose approval an organisation must obtain.

``organization`` is the tenant that pays us. ``customer`` is their client. Accreditation
is always produced for a named customer, which is why this module sits at the base of
the dependency chain rather than beside accreditation.
"""
