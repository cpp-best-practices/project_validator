select
    id,
    customer_id,
    amount
from {{ source('shop', 'orders') }}
