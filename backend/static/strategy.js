/* ICE-800 Integrated Strategy v1: in-memory manual preview; no browser persistence. */
(() => {
  const byId = id => document.getElementById(id);
  const addButton = byId('strategyAdd');
  if (!addButton) return;
  const debts = [];
  const currency = x => new Intl.NumberFormat('es-US', {style:'currency', currency:'USD'}).format(Number(x || 0));
  const val = id => byId(id).value;
  const number = id => Number(val(id) || 0);
  const optionalNumber = id => val(id).trim() === '' ? null : Number(val(id));

  function line(parent, text, tag = 'p', cls = 'muted') {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    el.textContent = text;
    parent.appendChild(el);
    return el;
  }
  function redrawDebts() {
    const list = byId('strategyDebts');
    list.replaceChildren();
    if (!debts.length) line(list,'Agrega una o varias deudas para comparar estrategias.');
    debts.forEach((d, index) => {
      const row = document.createElement('div'); row.className = 'item';
      line(row, `${d.name} · ${d.kind} · ${currency(d.balance)} · APR ${d.apr === null ? 'desconocida' : d.apr+'%'}`, 'b', '');
      const remove = document.createElement('button'); remove.type = 'button';
      remove.textContent = 'Quitar';
      remove.onclick = () => { debts.splice(index, 1); redrawDebts(); byId('strategyResults').replaceChildren(); };
      row.appendChild(remove); list.appendChild(row);
    });
  }
  function conditionalFields() {
    const kind = val('strategyKind');
    byId('strategyFederalRow').hidden = kind !== 'student_loan';
    byId('strategyGuaranteeRow').hidden = kind !== 'business_credit';
    byId('strategyPropertyRow').hidden = kind !== 'mortgage';
  }
  byId('strategyKind').addEventListener('change', conditionalFields);
  conditionalFields();
  addButton.onclick = () => {
    const name = val('strategyName').trim();
    const balance = number('strategyBalance');
    const apr = optionalNumber('strategyApr');
    const min = number('strategyMinimum');
    if (!name || !Number.isFinite(balance) || balance <= 0 || !Number.isFinite(min) || min < 0 || (apr !== null && (!Number.isFinite(apr) || apr < 0 || apr > 100))) {
      byId('strategyMessage').textContent='Introduce nombre, saldo positivo y valores financieros válidos.'; return;
    }
    if (debts.length >= 40) { byId('strategyMessage').textContent='Máximo 40 deudas por simulación.'; return; }
    const kind = val('strategyKind');
    const property_value = kind === 'mortgage' ? optionalNumber('strategyPropertyValue') : null;
    if (property_value !== null && !(property_value > 0)) { byId('strategyMessage').textContent='El valor de la propiedad debe ser positivo.'; return; }
    debts.push({name:name.slice(0,80), kind, balance, apr, minimum_payment:min,
      days_until_due:optionalNumber('strategyDueDays'),
      past_due:byId('strategyPastDue').checked,
      federal_student:kind==='student_loan' && byId('strategyFederal').checked,
      personal_guarantee:kind==='business_credit' && byId('strategyGuarantee').checked,
      property_value});
    byId('strategyMessage').textContent='Deuda agregada solo a esta simulación. No se ha guardado en una cuenta.';
    byId('strategyName').value=''; byId('strategyBalance').value=''; byId('strategyApr').value='';
    byId('strategyMinimum').value=''; byId('strategyDueDays').value='';
    byId('strategyPastDue').checked=false; redrawDebts();
  };
  byId('strategyAnalyze').onclick = async () => {
    const result = byId('strategyResults'); result.replaceChildren();
    const button = byId('strategyAnalyze'); button.disabled=true;
    byId('strategyMessage').textContent='Analizando los escenarios…';
    try {
      const bRevenue=optionalNumber('strategyBusinessRevenue');
      const bExpenses=optionalNumber('strategyBusinessExpenses');
      if ((bRevenue===null)!==(bExpenses===null)) throw Error('Completa ambos datos empresariales o deja ambos en blanco.');
      const body={
        monthly_income:number('strategyIncome'), essential_expenses:number('strategyEssentials'),
        monthly_insurance_premiums:number('strategyPremiums'), liquid_savings:number('strategySavings'),
        reserve_months:Number(val('strategyReserveMonths')), monthly_business_revenue:bRevenue,
        business_operating_expenses:bExpenses, debts,
      };
      const data = await api('/api/v1/strategy/preview', {method:'POST',body:JSON.stringify(body)});
      const s=data.summary;
      line(result,'Diagnóstico integral (simulación)','h3','');
      line(result,`Saldo disponible personal mensual: ${currency(s.personal_monthly_surplus)}`);
      line(result,`Obligaciones personales mensuales: ${currency(s.personal_monthly_obligations)}`);
      line(result,`Reserva objetivo: ${currency(s.reserve_goal)} · Falta: ${currency(s.reserve_gap)}`);
      line(result,`Deuda personal: ${currency(s.personal_debt_total)} · Crédito empresarial: ${currency(s.business_debt_total)}`);
      if(s.business_monthly_surplus!==null)line(result,`Flujo empresarial disponible: ${currency(s.business_monthly_surplus)}`);
      line(result,'Prioridades sugeridas','h3','');
      if(!data.actions.length)line(result,'No hay acciones que recomendar con estos datos.');
      data.actions.forEach((a,i)=>{
        const item=document.createElement('div'); item.className='item';
        line(item,`${i+1}. ${a.title}`,'b','');
        line(item,a.why);
        if(a.suggested_amount!==null)line(item,`Monto orientativo: ${currency(a.suggested_amount)}`);
        result.appendChild(item);
      });
      if(data.debts.length){
        line(result,'Evaluación contextual de obligaciones','h3','');
        data.debts.forEach(d=>{
          const el=document.createElement('div'); el.className='item';
          line(el,`${d.category}: ${d.name}`,'b','');
          line(el,`${d.classification} — ${d.classification_reason}`);
          if(d.monthly_interest_estimate!==null)line(el,`Interés mensual aproximado: ${currency(d.monthly_interest_estimate)}`);
          if(d.loan_to_value!==null)line(el,`Deuda / valor de vivienda: ${(100*d.loan_to_value).toFixed(1)}%`);
          result.appendChild(el);
        });
      }
      if(data.warnings.length){line(result,'Información pendiente y advertencias','h3','');data.warnings.forEach(w=>line(result,w));}
      line(result,'Simulación informativa. No calcula puntuaciones futuras, no garantiza ahorros ni ejecuta operaciones. Verifica términos con los proveedores.');
      byId('strategyMessage').textContent='Análisis realizado sin guardar el formulario en la base de datos.';
    }catch(e){
      const message=typeof e.message==='string'?e.message:'No se pudo completar la simulación.';
      byId('strategyMessage').textContent=message;
    }finally{button.disabled=false;}
  };
  redrawDebts();
})();
