# ToolTruth SDK
Install locally with `pip install -e .`.

```python
from tooltruth import ToolTruthClient
client=ToolTruthClient("http://127.0.0.1:8000")
print(client.call("ecommerce","get_inventory",{"product_id":"SKU-100"}))
```
