odoo.define('yousentech_car_appointments.calendar', function (require) {
'use strict';
var AbstractAction = require('web.AbstractAction');
var core = require('web.core');
var rpc = require('web.rpc');
var qweb = core.qweb;
function iso(d){return [d.getFullYear(),('0'+(d.getMonth()+1)).slice(-2),('0'+d.getDate()).slice(-2)].join('-');}
function day(s){return new Date(s+'T12:00:00');}
function add(d,n){return new Date(d.getFullYear(),d.getMonth(),d.getDate()+n,12);}
function fmt(d,opts,cal){try{return new Intl.DateTimeFormat('ar-SA-u-ca-'+cal,opts).format(d);}catch(e){return iso(d);}}
var Calendar=AbstractAction.extend({
 events:{'click .ycc-prev':'_prev','click .ycc-next':'_next','click .ycc-today':'_today','click .ycc-mode-week':'_week','click .ycc-mode-month':'_month','change .ycc-branch':'_branch','click .ycc-cell':'_period','click .ycc-new':'_new'},
 init:function(){this._super.apply(this,arguments);this.mode='week';this.anchor=day(iso(new Date()));this.branchId=null;this.payload={branches:[],slots:[],appointments:[],exceptions:[]};},
 start:function(){return this._load();},
 _range:function(){var d=this.anchor;if(this.mode==='month'){return [new Date(d.getFullYear(),d.getMonth(),1,12),new Date(d.getFullYear(),d.getMonth()+1,1,12)];}var offset=(d.getDay()+1)%7,start=add(d,-offset);return [start,add(start,7)];},
 _load:function(){var self=this,r=this._range();return rpc.query({route:'/ycc/calendar/data',params:{branch_id:this.branchId,start:iso(r[0]),end:iso(r[1])}}).then(function(data){if(data.error){self.$el.text(data.error);return;}self.payload=data;self.branchId=data.branch_id||null;self._render();});},
 _render:function(){var r=this._range(),data=this.payload,days=[],slots=data.slots||[],bookings=data.appointments||[];
 for(var d=r[0];d<r[1];d=add(d,1)){days.push({date:iso(d),weekday:d.getDay(),label:fmt(d,{weekday:'short',day:'numeric',month:'short'},'gregory'),hijri:fmt(d,{day:'numeric',month:'short'},'islamic-umalqura')});}
 var rows=slots.map(function(s){return {name:s.name,cells:days.map(function(d){var active=!s.days.length||s.days.indexOf((d.weekday+6)%7)!==-1,closed=(data.exceptions||[]).some(function(e){return e.date===d.date&&(!e.slot_id||e.slot_id===s.id);}),count=bookings.filter(function(b){return b.date===d.date&&b.slot_id===s.id;}).length,open=active&&!closed;return {date:d.date,slot_id:s.id,capacity:s.capacity,count:count,open:open,remaining:Math.max(0,s.capacity-count),css:!open?'closed':count>=s.capacity?'full':count>=s.capacity*.75?'busy':'free'};})};});
 var capacity=0,occupied=0;rows.forEach(function(row){row.cells.forEach(function(c){if(c.open){capacity+=c.capacity;occupied+=c.count;}});});
 this.$el.html(qweb.render('ycc.Calendar',{branches:data.branches||[],branchId:this.branchId,days:days,rows:rows,mode:this.mode,periodLabel:fmt(r[0],{day:'numeric',month:'long',year:'numeric'},'gregory')+' — '+fmt(add(r[1],-1),{day:'numeric',month:'long',year:'numeric'},'gregory'),hijriLabel:fmt(r[0],{day:'numeric',month:'long',year:'numeric'},'islamic-umalqura')+' — '+fmt(add(r[1],-1),{day:'numeric',month:'long',year:'numeric'},'islamic-umalqura'),summary:{capacity:capacity,occupied:occupied,confirmed:bookings.filter(function(b){return b.state==='confirmed'||b.state==='done';}).length,provisional:bookings.filter(function(b){return b.state==='provisional'||b.state==='contacting';}).length}}));},
 _prev:function(){this.anchor=this.mode==='month'?new Date(this.anchor.getFullYear(),this.anchor.getMonth()-1,1,12):add(this.anchor,-7);return this._load();},
 _next:function(){this.anchor=this.mode==='month'?new Date(this.anchor.getFullYear(),this.anchor.getMonth()+1,1,12):add(this.anchor,7);return this._load();},
 _today:function(){this.anchor=day(iso(new Date()));return this._load();},
 _week:function(){this.mode='week';return this._load();},
 _month:function(){this.mode='month';return this._load();},
 _branch:function(e){this.branchId=parseInt(e.currentTarget.value,10);return this._load();},
 _new:function(){this.do_action({type:'ir.actions.act_window',res_model:'ycc.appointment',views:[[false,'form']],target:'current'});},
 _period:function(e){var date=e.currentTarget.getAttribute('data-date'),slotId=parseInt(e.currentTarget.getAttribute('data-slot'),10),slot=(this.payload.slots||[]).filter(function(s){return s.id===slotId;})[0];if(!slot)return;
 var bookings=(this.payload.appointments||[]).filter(function(b){return b.date===date&&b.slot_id===slotId;}),branch=(this.payload.branches||[]).filter(function(b){return b.id===this.branchId;},this)[0],self=this;
 var html=qweb.render('ycc.PeriodModal',{date:date,slotId:slotId,slotName:slot.name,branchName:branch?branch.name:'',capacity:slot.capacity,bookings:bookings,confirmed:bookings.filter(function(b){return b.state==='confirmed'||b.state==='done';}).length,provisional:bookings.filter(function(b){return b.state==='provisional'||b.state==='contacting';}).length});
 var $modal=$('<div class="modal fade ycc-modal" tabindex="-1" role="dialog"/>').html(html);$('body').append($modal);
 $modal.on('click','.ycc-close',function(){$modal.modal('hide');});
 $modal.on('click','.ycc-open-booking',function(){var id=parseInt($(this).attr('data-id'),10);$modal.modal('hide');self.do_action({type:'ir.actions.act_window',res_model:'ycc.appointment',res_id:id,views:[[false,'form']],target:'current'});});
 $modal.on('click','.ycc-create-period',function(){$modal.modal('hide');self.do_action({type:'ir.actions.act_window',res_model:'ycc.appointment',views:[[false,'form']],target:'current',context:{default_branch_id:self.branchId,default_slot_id:slotId,default_date:date}});});
 $modal.on('hidden.bs.modal',function(){$modal.remove();self._load();});$modal.modal('show');}
});core.action_registry.add('ycc_appointment_calendar',Calendar);return Calendar;
});
