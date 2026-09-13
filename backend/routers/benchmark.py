import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from auth import current_admin
from benchmark.runner import BenchmarkRunner
from models import BenchmarkRun
from pydantic import BaseModel

router=APIRouter(prefix="/benchmark",tags=["benchmark"])
class RunRequest(BaseModel):
    domain:str="ecommerce"
    mode:str="tooltruth"

@router.post("/run")
def run(body:RunRequest,db:Session=Depends(get_db),_=Depends(current_admin)):
    if body.domain not in {"ecommerce","devops","travel"}: raise HTTPException(400,"Unsupported domain")
    if body.mode not in {"agent_alone","prompt_reflection","schema_only","stateless_policy","tooltruth"}: raise HTTPException(400,"Unsupported mode")
    return BenchmarkRunner(db).run(body.domain,body.mode)

@router.get("/results")
def results(db:Session=Depends(get_db),_=Depends(current_admin)):
    rows=db.query(BenchmarkRun).order_by(BenchmarkRun.id.desc()).limit(100).all()
    return {"runs":[{**json.loads(r.summary_json),"run_id":r.run_id,"created_at":r.created_at.isoformat()} for r in rows]}

@router.get("/results/{run_id}")
def result(run_id:str,db:Session=Depends(get_db),_=Depends(current_admin)):
    row=db.query(BenchmarkRun).filter(BenchmarkRun.run_id==run_id).first()
    if not row: raise HTTPException(404,"Benchmark run not found")
    return {**json.loads(row.summary_json),"run_id":row.run_id,"results":json.loads(row.results_json)}
