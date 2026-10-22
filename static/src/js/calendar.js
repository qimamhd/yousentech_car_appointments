odoo.define('yousentech_car_appointments.calendar', function (require) {
'use strict';
var AbstractAction = require('web.AbstractAction');
var core = require('web.core');
var rpc = require('web.rpc');
var qweb = core.qweb;
function iso(d){return [d.getFullYear(),('0'+(d.getMonth()+1)).slice(-2),('0'+d.getDate()).slice(-2)].join('-');}
function day(s){return new Date(s+'T12:00:00');}
function add(d,n){return new Date(d.getFullYear(),d.getMonth(),d.getDate()+n,12);}
function fmt(d,opts,cal,lang){try{return new Intl.DateTimeFormat(lang+(cal?'-u-ca-'+cal:''),opts).format(d);}catch(e){return iso(d);}}
var Calendar=AbstractAction.extend({
 events:{'click .ycc-prev':'_prev','click .ycc-next':'_next','click .ycc-today':'_today','click .ycc-mode-week':'_week','click .ycc-mode-month':'_month','change .ycc-branch':'_branch','click .ycc-cell':'_period','click .ycc-new':'_new','click .ycc-installation-count':'_installationDay'},
 init:function(){this._super.apply(this,arguments);this.mode='week';this.anchor=day(iso(new Date()));this.branchId=null;this.payload={branches:[],slots:[],appointments:[],exceptions:[]};},
 start:function(){
    var self=this;
    this._calendarAlive=true;
    this._onWindowFocus=function(){if(self._calendarAlive){self._load(true);}};
    window.addEventListener('focus',this._onWindowFocus);
    this._refreshTimer=window.setInterval(function(){
        if(self._calendarAlive && !document.hidden && self.$el.is(':visible') &&
           !$('.ycc-modal:visible').length){self._load(true);}
    },10000);
    return this._load();
 },
 destroy:function(){
    this._calendarAlive=false;
    if(this._refreshTimer){window.clearInterval(this._refreshTimer);this._refreshTimer=null;}
    if(this._onWindowFocus){window.removeEventListener('focus',this._onWindowFocus);}
    return this._super.apply(this,arguments);
 },
 _range:function(){var d=this.anchor;if(this.mode==='month'){return [new Date(d.getFullYear(),d.getMonth(),1,12),new Date(d.getFullYear(),d.getMonth()+1,1,12)];}var offset=(d.getDay()+1)%7,start=add(d,-offset);return [start,add(start,7)];},
 _load:function(silent){
    var self=this,r=this._range();
    if(this._loading){this._reloadQueued=true;return this._loading;}
    this._loading=rpc.query({route:'/ycc/calendar/data',params:{
        branch_id:this.branchId,start:iso(r[0]),end:iso(r[1])
    }}).then(function(data){
        if(!self._calendarAlive){return;}
        if(data.error){if(!silent){self.$el.text(data.error);}return;}
        var signature=JSON.stringify(data);
        // Don't disturb the user's scroll or the current calendar on an unchanged poll.
        if(silent && signature===self._lastSignature){return;}
        var scroll=self.$('.ycc-grid-wrap'),top=scroll.scrollTop(),left=scroll.scrollLeft();
        self.payload=data;
        self.branchId=data.branch_id||null;
        self._lastSignature=signature;
        self._render();
        if(silent){self.$('.ycc-grid-wrap').scrollTop(top).scrollLeft(left);}
    }).then(function(){self._loading=null;if(self._reloadQueued){self._reloadQueued=false;return self._load();}},function(err){
        self._loading=null;
        if(!silent){throw err;}
    });
    return this._loading;
 },
 _render:function(){var r=this._range(),data=this.payload,slots=data.slots||[],bookings=data.appointments||[],lang=(data.lang||'en_US').replace('_','-'),isRtl=/^(ar|fa|ur|he)(-|$)/i.test(lang),days=[];
 for(var d=r[0];d<r[1];d=add(d,1)){days.push({date:iso(d),weekday:d.getDay(),label:fmt(d,{weekday:'long',day:'numeric',month:'short'},'gregory',lang),hijri:fmt(d,{day:'numeric',month:'short'},'islamic-umalqura',lang)});}
 var today=data.today||iso(new Date());
 // Daily capacity: count each appointment once per day, not once per slot.
 var daily={};
 days.forEach(function(d){
   var seen={};bookings.forEach(function(b){
     if((b.periods||[]).some(function(p){return p.date===d.date;})){seen[b.id]=true;}
   });
   daily[d.date]={count:Object.keys(seen).length,capacity:data.daily_capacity||0};
 });
 var rows=days.map(function(d){var dailyInfo=daily[d.date]||{count:0,capacity:0};return {date:d.date,label:d.label,hijri:d.hijri,dailyCount:dailyInfo.count,dailyCapacity:dailyInfo.capacity,dailyPercent:dailyInfo.capacity?Math.min(100,Math.round(dailyInfo.count*100/dailyInfo.capacity)):0,installationCount:((data.installation_by_day||{})[d.date]||[]).length,cells:slots.map(function(s){
   var active=!s.days.length||s.days.indexOf((d.weekday+6)%7)!==-1,
       closed=(data.exceptions||[]).some(function(e){return e.date===d.date&&(!e.slot_id||e.slot_id===s.id);}),
       list=bookings.filter(function(b){return (b.periods||[]).some(function(p){return p.date===d.date&&p.slot_id===s.id;});}),
       count=list.length,arrivedCount=list.filter(function(b){return b.state==='done';}).length,
       open=active&&!closed,past=d.date<today,
       css=!open?'closed':past?'past':dailyInfo.count>=dailyInfo.capacity?'full':dailyInfo.count>=dailyInfo.capacity*.75?'busy':dailyInfo.count?'partial':'free';
   return {date:d.date,slot_id:s.id,capacity:dailyInfo.capacity,count:count,dailyCount:dailyInfo.count,open:open,
     remaining:Math.max(0,dailyInfo.capacity-dailyInfo.count),css:css,bookings:list,past:past,firstClient:list.length?list[0].client:'',bookingStatus:list.length?(arrivedCount?'وصلت السيارة':list[0].state==='confirmed'?'مؤكد':'مبدئي'):'',
     arrivedCount:arrivedCount,hasArrived:arrivedCount>0,
     spanCount:list.filter(function(b){return (b.periods||[]).length>1;}).length,
     hasSpan:list.some(function(b){return (b.periods||[]).length>1;})};})};});
 var capacity=days.length*(data.daily_capacity||0),occupied=days.reduce(function(total,d){return total+(daily[d.date]||{count:0}).count;},0);
 var unique={};bookings.forEach(function(b){unique[b.id]=b;});var all=Object.keys(unique).map(function(k){return unique[k];});
 var timeRows=slots.map(function(s,index){return {name:s.name,cells:rows.map(function(row){return row.cells[index];})};});
 var fullDays=rows.filter(function(row){return row.dailyCapacity>0 && row.dailyCount>=row.dailyCapacity;}).length;
 this.$el.html(qweb.render('ycc.Calendar',{branches:data.branches||[],branchId:this.branchId,days:days,slots:slots,rows:rows,timeRows:timeRows,mode:this.mode,arrivalOnly:!!data.arrival_only,canCreate:!!data.can_create,calendarDir:isRtl?'rtl':'ltr',periodLabel:fmt(r[0],{day:'numeric',month:'long',year:'numeric'},'gregory',lang)+' — '+fmt(add(r[1],-1),{day:'numeric',month:'long',year:'numeric'},'gregory',lang),hijriLabel:fmt(r[0],{day:'numeric',month:'long',year:'numeric'},'islamic-umalqura',lang)+' — '+fmt(add(r[1],-1),{day:'numeric',month:'long',year:'numeric'},'islamic-umalqura',lang),summary:{dailyCapacity:data.daily_capacity||0,averagePct:capacity?Math.round(occupied*100/capacity):0,fullDays:fullDays,capacity:capacity,occupied:occupied,confirmed:all.filter(function(b){return b.state==='confirmed';}).length,provisional:all.filter(function(b){return b.state==='provisional'||b.state==='contacting';}).length}}));},
 _installationDay:function(e){
   e.preventDefault();e.stopPropagation();
   var selected=e.currentTarget.getAttribute('data-date'),orders=((this.payload.installation_by_day||{})[selected]||[]),self=this;
   var html=qweb.render('ycc.InstallationDayModal',{date:selected,orders:orders});
   var $modal=$('<div class="modal fade ycc-modal" tabindex="-1" role="dialog"/>').html(html);
   $('body').append($modal);
   $modal.on('click','.ycc-close',function(){$modal.modal('hide');});
   $modal.on('click','.ycc-open-order',function(ev){
      ev.preventDefault();var id=parseInt($(this).attr('data-id'),10);
      if(!id)return;
      $modal.one('hidden.bs.modal',function(){self.do_action({type:'ir.actions.act_window',res_model:'wo.installation.order.mst',res_id:id,views:[[false,'form']],view_mode:'form',target:'current'});});
      $modal.modal('hide');
   });
   $modal.on('hidden.bs.modal',function(){$modal.remove();});
   $modal.modal('show');
 },
 _prev:function(){this.anchor=this.mode==='month'?new Date(this.anchor.getFullYear(),this.anchor.getMonth()-1,1,12):add(this.anchor,-7);return this._load();},
 _next:function(){this.anchor=this.mode==='month'?new Date(this.anchor.getFullYear(),this.anchor.getMonth()+1,1,12):add(this.anchor,7);return this._load();},
 _today:function(){this.anchor=day(iso(new Date()));return this._load();},
 _week:function(){this.mode='week';return this._load();},
 _month:function(){this.mode='month';return this._load();},
 _branch:function(e){this.branchId=parseInt(e.currentTarget.value,10);return this._load();},
 _new:function(){if(!this.payload.can_create){return;}this.do_action({type:'ir.actions.act_window',res_model:'ycc.appointment',views:[[false,'form']],target:'current'});},
 _period:function(e){var date=e.currentTarget.getAttribute('data-date'),slotId=parseInt(e.currentTarget.getAttribute('data-slot'),10),slot=(this.payload.slots||[]).filter(function(s){return s.id===slotId;})[0];if(!slot)return;
 var bookings=(this.payload.appointments||[]).filter(function(b){return (b.periods||[]).some(function(p){return p.date===date&&p.slot_id===slotId;});}),branch=(this.payload.branches||[]).filter(function(b){return b.id===this.branchId;},this)[0],self=this;
 var html=qweb.render('ycc.PeriodModal',{date:date,slotId:slotId,slotName:slot.name,branchName:branch?branch.name:'',capacity:this.payload.daily_capacity||slot.capacity,dailyCount:(function(){var seen={};(self.payload.appointments||[]).forEach(function(b){if((b.periods||[]).some(function(p){return p.date===date;})){seen[b.id]=true;}});return Object.keys(seen).length;})(),bookings:bookings,confirmed:bookings.filter(function(b){return b.state==='confirmed';}).length,arrived:bookings.filter(function(b){return b.state==='done';}).length,provisional:bookings.filter(function(b){return b.state==='provisional'||b.state==='contacting';}).length,canCreate:!!this.payload.can_create,canInstall:!!this.payload.can_create||!!this.payload.arrival_only});
 var $modal=$('<div class="modal fade ycc-modal" tabindex="-1" role="dialog"/>').html(html);$('body').append($modal);
 $modal.on('click','.ycc-close',function(){$modal.modal('hide');});
 // Open the actual appointment when clicking anywhere on its card.
 // Wait until the Bootstrap modal is fully closed before navigating.
 var openingBooking=false;
 function openBooking(e){
     if(e){e.preventDefault();e.stopPropagation();}
     if(openingBooking)return;
     var id=parseInt($(this).closest('.ycc-booking').attr('data-id'),10);
     if(!id)return;
     openingBooking=true;
     $modal.one('hidden.bs.modal.yccOpen',function(){
         $modal.remove();
         self.do_action({type:'ir.actions.act_window',name:'تفاصيل الحجز',
             res_model:'ycc.appointment',res_id:id,views:[[false,'form']],
             view_mode:'form',target:'current'});
     });
     $modal.modal('hide');
 }
 $modal.on('click','.ycc-open-installation',function(e){
     e.preventDefault();e.stopPropagation();
     var id=parseInt($(this).attr('data-id'),10),$btn=$(this);
     if(!id||$btn.prop('disabled'))return;
     $btn.prop('disabled',true);
     rpc.query({route:'/ycc/calendar/installation_action',params:{appointment_id:id}}).then(function(action){
         if(action.error){$btn.prop('disabled',false);alert(action.error);return;}
         $modal.one('hidden.bs.modal.yccInstall',function(){$modal.remove();self.do_action(action);});
         $modal.modal('hide');
     }).catch(function(){$btn.prop('disabled',false);});
 });
 $modal.on('click','.ycc-booking',openBooking);
 $modal.on('keydown','.ycc-booking',function(e){
     if(e.key==='Enter'||e.key===' '||e.which===13||e.which===32)openBooking.call(this,e);
 });
 $modal.on('click','.ycc-forecast-period',function(){
     var $btn=$(this);$btn.prop('disabled',true);
     rpc.query({route:'/ycc/calendar/forecast',params:{branch_id:self.branchId,date:date}})
       .then(function(result){
         var $msg=$modal.find('.ycc-forecast-result');
         if(!$msg.length){$msg=$('<div class="ycc-forecast-result" role="status"/>');$modal.find('.modal-body').prepend($msg);}
         $msg.empty();
         $msg.append($('<div class="ycc-forecast-summary"/>').text(result.message||'تعذر التحقق.'));
         if(result.status!=='ok'){return;}
         var $stats=$('<div class="ycc-forecast-stats"/>');
         [['موعد التسليم اليوم',result.today_count],['موعد التسليم لاحقاً',result.later_count],['وصلت حسب المواعيد',result.arrived],['مطابقة بالاسم',result.matched_customers]].forEach(function(pair){
           $stats.append($('<div class="ycc-forecast-stat"/>').append($('<strong/>').text(pair[1]),$('<small/>').text(pair[0])));
         });
         $msg.append($stats);
         var $today=$('<section class="ycc-forecast-today"/>');
         $today.append($('<h5 class="ycc-forecast-title"/>').text('موعد التسليم في اليوم المحدد ('+(result.today_count||0)+')'));
         function renderForecastRows(items, emptyText){
           var $list=$('<div class="ycc-forecast-list"/>');
           (items||[]).forEach(function(item){
             $list.append($('<div class="ycc-forecast-line"/>').append(
               $('<strong/>').text(item.customer),
               $('<span/>').text(item.order+' · التسليم: '+item.delivery_date+' · الفترة: '+(item.delivery_period||'غير محددة')),
               $('<small/>').text(item.status+(item.matched_appointment?' · له حجز وصول بالاسم':''))));
           });
           if(!items||!items.length){$list.append($('<div class="ycc-forecast-empty"/>').text(emptyText));}
           return $list;
         }
         $today.append(renderForecastRows(result.orders,'لا توجد أوامر موعد تسليمها في هذا اليوم.'));
         $msg.append($today);
         if(result.later_count){
           var $later=$('<details class="ycc-forecast-later"/>');
           $later.append($('<summary/>').text('موعد التسليم لاحقاً ('+result.later_count+') — عرض التفاصيل'));
           $later.append(renderForecastRows(result.later_orders,'لا توجد أوامر لاحقة.'));
           $msg.append($later);
         }

       },function(){
         var $msg=$modal.find('.ycc-forecast-result');
         if(!$msg.length){$msg=$('<div class="ycc-forecast-result"/>');$modal.find('.modal-body').prepend($msg);}
         $msg.empty().append($('<div class="alert alert-warning"/>').text('تعذر التحقق من أوامر التركيب.'));
       })
       .then(function(){$btn.prop('disabled',false);});
 });
 $modal.on('click','.ycc-create-period',function(){if(!self.payload.can_create){return;}$modal.modal('hide');self.do_action({type:'ir.actions.act_window',res_model:'ycc.appointment',views:[[false,'form']],target:'current',context:{default_branch_id:self.branchId,default_slot_id:slotId,default_date:date}});});
 $modal.on('hidden.bs.modal',function(){if(!openingBooking){$modal.remove();self._load();}});$modal.modal('show');}
});core.action_registry.add('ycc_appointment_calendar',Calendar);return Calendar;
});
