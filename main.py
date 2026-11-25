import os
from datetime import date
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client

load_dotenv()
db = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class NewProduct(BaseModel):
    name: str
    price: float
    stock: int = 0
    image_url: str | None = None

class PriceUpdate(BaseModel):
    price: float

class StockUpdate(BaseModel):
    stock: int

class OrderItemIn(BaseModel):
    product_id: int
    quantity: int

class NewOrder(BaseModel):
    customer_name: str
    phone: str | None = None
    items: list[OrderItemIn]

# ---------- products ----------
@app.get("/products")
def list_products():
    return db.table("products").select("*").order("id").execute().data

@app.post("/products")
def add_product(p: NewProduct):
    return db.table("products").insert(p.model_dump()).execute().data[0]

@app.get("/products/search/{name}")
def find_product(name: str):
    return db.table("products").select("*").ilike("name", f"%{name}%").execute().data

@app.patch("/products/{pid}/price")
def update_price(pid: int, body: PriceUpdate):
    if body.price <= 0:
        raise HTTPException(400, "Price must be above 0")
    res = db.table("products").update({"price": body.price}).eq("id", pid).execute()
    if not res.data:
        raise HTTPException(404, "Product not found")
    return res.data[0]

@app.patch("/products/{pid}/stock")
def update_stock(pid: int, body: StockUpdate):
    if body.stock < 0:
        raise HTTPException(400, "Stock can't be negative")
    res = db.table("products").update({"stock": body.stock}).eq("id", pid).execute()
    if not res.data:
        raise HTTPException(404, "Product not found")
    return res.data[0]

@app.delete("/products/{pid}")
def delete_product(pid: int):
    db.table("products").delete().eq("id", pid).execute()
    return {"deleted": pid}

# ---------- orders ----------
@app.post("/orders")
def place_order(o: NewOrder):
    total = 0
    lines = []
    for item in o.items:
        prod = db.table("products").select("*").eq("id", item.product_id).execute().data
        if not prod:
            raise HTTPException(404, f"Product {item.product_id} not found")
        prod = prod[0]
        if prod["stock"] < item.quantity:
            raise HTTPException(400, f"Not enough stock for {prod['name']}")
        total += prod["price"] * item.quantity
        lines.append((prod, item.quantity))

    order = db.table("orders").insert({
        "customer_name": o.customer_name,
        "phone": o.phone,
        "total": total,
    }).execute().data[0]

    for prod, qty in lines:
        db.table("order_items").insert({
            "order_id": order["id"],
            "product_id": prod["id"],
            "quantity": qty,
            "price": prod["price"],
        }).execute()
        db.table("products").update({"stock": prod["stock"] - qty}).eq("id", prod["id"]).execute()
    return order

@app.get("/orders")
def list_orders():
    return db.table("orders").select("*, order_items(*, products(name))").order("id", desc=True).execute().data

@app.patch("/orders/{oid}/status/{status}")
def update_status(oid: int, status: str):
    if status not in ("pending", "packed", "shipped", "delivered", "cancelled"):
        raise HTTPException(400, "Bad status")
    res = db.table("orders").update({"status": status}).eq("id", oid).execute()
    if not res.data:
        raise HTTPException(404, "Order not found")
    return res.data[0]

# ---------- sales summary ----------
@app.get("/sales/summary")
def sales_summary():
    today = date.today().isoformat()
    rows = db.table("orders").select("total, created_at").gte("created_at", today).execute().data
    return {"date": today, "orders": len(rows), "revenue": sum(r["total"] for r in rows)}