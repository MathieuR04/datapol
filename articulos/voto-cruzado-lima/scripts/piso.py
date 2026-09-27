import duckdb, sys
P='/Users/mathieurojas/Documents/datapol/articulos/erm/2022/data/processed/'
con=duckdb.connect()
con.sql(f"""
create table m as
select a.mesa, a.ubigeo_distrito ubi, a.local, a.votaron emit,
  a.votos_validos vp, b.votos_validos vd, a.votos_blancos bp, b.votos_blancos bd,
  a.votos_nulos np_, b.votos_nulos nd
from '{P}computo_mesa_ERM2022.parquet' a join '{P}computo_mesa_ERM2022.parquet' b
 on a.mesa=b.mesa and a.tipo='03' and b.tipo='04'
where a.ubigeo_distrito like '1401%' and a.observacion like 'CONTAB%' and b.observacion like 'CONTAB%' and a.votaron>0""")
con.sql(f"""
create table r as
select mesa, agrupacion org, sum(votos) filter(where tipo='03') p, sum(votos) filter(where tipo='04') d
from '{P}resultados_mesa_ERM2022.parquet' where ubigeo_distrito like '1401%' group by 1,2""")
con.sql("""
create table f as
select m.*, coalesce(s.recto,0) recto_org
from m left join (select mesa, sum(least(coalesce(p,0),coalesce(d,0))) recto from r group by 1) s using(mesa)""")
con.sql("""create table f2 as select *,
  recto_org + least(bp,bd) + least(np_,nd) recto_amplio from f""")
print(con.sql("""select count(*) mesas, sum(emit) emit, sum(vp) vp, sum(vd) vd,
 1-sum(recto_amplio)/sum(emit) piso_emit_amplio,
 1-sum(recto_org)/sum(emit) piso_emit_org,
 1-sum(recto_org)/sum(least(vp,vd)) piso_sobre_validos_min
 from f2"""))
# same floor computed at district aggregate (to show mesa gain)
print(con.sql("""with dp as (select m.ubi, org, sum(coalesce(p,0)) p, sum(coalesce(d,0)) d from r join m using(mesa) group by 1,2),
 e as (select ubi, sum(emit) emit, sum(bp) bp, sum(bd) bd, sum(np_) np_, sum(nd) nd from m group by 1)
 select 1-(sum(x.recto)+sum(least(bp,bd))+sum(least(np_,nd)))/sum(emit) piso_distrital_agregado
 from e join (select ubi, sum(least(p,d)) recto from dp group by 1) x using(ubi)"""))
con.sql("copy f2 to '"+sys.argv[1]+"/piso_mesa.parquet'")
con.sql("copy r to '"+sys.argv[1]+"/votos_mesa_lima.parquet'")
