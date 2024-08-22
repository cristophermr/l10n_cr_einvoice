from odoo import models, fields, api, exceptions
from odoo.exceptions import ValidationError
from datetime import datetime,timezone
from lxml.etree import Element, fromstring, parse, tostring, XMLParser
# from openerp.osv import osv
from odoo.osv import osv
#from openerp.tools.translate import _
from odoo.tools.translate import _
from .xslt import __path__ as path
import lxml.etree as ET
import pytz
import json
import re
import requests
import base64
import xmltodict
import logging
import time
#import os

log = _logger = _logging = logging.getLogger(__name__)

TYPE2REFUND = {
    'out_invoice': 'out_refund',        # Customer Invoice
    'in_invoice': 'in_refund',          # Vendor Bill
    'out_refund': 'out_invoice',        # Customer Credit Note
    'in_refund': 'in_invoice',          # Vendor Credit Note
}

class AccountMoveFunctions(models.Model):
    _inherit = "account.move"
    
    @api.constrains('fe_doc_ref')
    def _constrains_fe_doc_ref(self):
        _logger.info(f"===== _constrains_fe_doc_ref para nota credito o nota debito")
        if self.name[8:10] == '03' or self.name[8:10] == '02':
            doc = self.search([('name', '=', self.fe_doc_ref)])
            if not doc:
                raise ValidationError('El documento de referencia no existe')
                
    def _rate(self,date):
        _logger.info(f"DEF101 =====")
        rate_obj = self.env['res.currency.rate'].search([('name','=',date),('company_id','=',self.company_id.id)])
        if rate_obj:
            rate_calculation = 1 / rate_obj.rate
            rate_name =  datetime.strptime(rate_obj.name,"%Y-%m-%d")
            self.fe_currency_rate = "Fecha : %s || Cambio: %s" % (rate_name.strftime("%d/%m/%Y"), round(rate_calculation , 2) )
            return
        else:
            update_currency = getattr(self.company_id, "_update_currency_bccr", None)
            if callable(update_currency):
                success = self.company_id._update_currency_bccr(date)
                if success:
                    return self._rate(date)
                else:
                    self.fe_currency_rate = "Se produjo un error"
                    return
            else:
                self.fe_currency_rate = "No existe el tipo de cambio"
                return 
    
    @api.depends('company_id')
    def _get_country_code(self):
        log.info('--> 1575319718 _get_country_code ')
        for s in self:
            s.fe_current_country_company_code = s.company_id.country_id.code


    
    def _compute_exoneraciones(self):
                _logger.info(f"DEF132 ===== _compute_exoneraciones")
                for record in self:
                  record.TotalServExonerado = 0
                  record.TotalMercExonerada = 0
                  record.TotalExonerado = 0

                  if record.fiscal_position_id:
                      for i in record.invoice_line_ids:
                            if not i.tax_ids:
                                continue
                            fiscal = record.fiscal_position_id.tax_ids.search([('tax_dest_id','=',i.tax_ids[0].id)])
                            old_tax = record.fiscal_position_id.tax_ids.search([('tax_dest_id','=',i.tax_ids[0].id)]).tax_src_id
                            LineaImpuestoTarifa = round(old_tax.amount,2)
                            percent = fiscal.tax_src_id.amount - fiscal.tax_dest_id.amount
                            if i.product_id.type == 'service':
                                record.TotalServExonerado =   \
                                    record.TotalServExonerado + i.price_subtotal * ( percent / LineaImpuestoTarifa )
                            else:
                                record.TotalMercExonerada = record.TotalMercExonerada + i.price_subtotal * ( percent / LineaImpuestoTarifa )

                      record.TotalExonerado = record.TotalServExonerado + record.TotalMercExonerada
    
    def _compute_gravados_exentos(self):
        _logger.info(f"DEF92 ===== _compute_gravados_exentos: {self}")
        for record in self:
            fiscal_position_id = record.fiscal_position_id
            _logger.info(f"DEF98 fiscal_position_id: {fiscal_position_id.id}- {fiscal_position_id.name}\n")
            for i in record.invoice_line_ids:
                if not i.tax_ids:
                    continue
                _logger.info(f"DEF96 invoice_line description: {i.name}\n")
                fiscal = record.fiscal_position_id.tax_ids.search([('tax_dest_id','=',i.tax_ids[0].id)]) 
                
                old_tax = record.fiscal_position_id.tax_ids.search([('tax_dest_id','=',i.tax_ids[0].id)]).tax_src_id        
                LineaImpuestoTarifa = round(old_tax.amount,2)
                _logger.info(f"DEF101 invoice_line LineaImpuestoTarifa: {LineaImpuestoTarifa}\n")
                percent = fiscal.tax_src_id.amount - fiscal.tax_dest_id.amount
                LineaMontoTotal = round((i.quantity * i.price_unit),5)
                if i.product_id.type == 'service':
                            #asking for tax for know if the product is Tax Free
                            if i.tax_ids:
                                if record.fiscal_position_id:
                                    record.fe_total_servicio_gravados = record.fe_total_servicio_gravados + (1-percent/LineaImpuestoTarifa) * LineaMontoTotal
                                else:
                                    record.fe_total_servicio_gravados = record.fe_total_servicio_gravados + LineaMontoTotal
                            else:
                                record.fe_total_servicio_exentos = record.fe_total_servicio_exentos + LineaMontoTotal
                else:
                            if i.tax_ids:
                                if record.fiscal_position_id:
                                    record.fe_total_mercancias_gravadas = record.fe_total_mercancias_gravadas + (1-percent/LineaImpuestoTarifa) * LineaMontoTotal
                                else:
                                    record.fe_total_mercancias_gravadas = record.fe_total_mercancias_gravadas + LineaMontoTotal #LineaSubTotal
                            else:
                                record.fe_total_mercancias_exentas = record.fe_total_mercancias_exentas + LineaMontoTotal #LineaSubTotal

            record.fe_total_gravado = record.fe_total_servicio_gravados + record.fe_total_mercancias_gravadas
            record.fe_total_exento = record.fe_total_mercancias_exentas + record.fe_total_servicio_exentos


            _logger.info(f"record.fe_total_servicio_gravados: {record.fe_total_servicio_gravados}")
            _logger.info(f"record.fe_total_servicio_exentos: {record.fe_total_servicio_exentos}")
            _logger.info(f"record.fe_total_mercancias_gravadas: {record.fe_total_servicio_gravados}")
            _logger.info(f"record.fe_total_mercancias_exentas: {record.fe_total_servicio_exentos}")
            _logger.info(f"record.fe_total_gravado: {record.fe_total_gravado}")
            _logger.info(f"record.fe_total_exento: {record.fe_total_exento}")
            
            STOP122

    def _compute_total_descuento(self):
        _logger.info(f"DEF185 ===== _compute_total_descuento")
        log.info('--> factelec/_compute_total_descuento')
        for s in self:
            totalDiscount = 0
            for i in s.invoice_line_ids:
                if i.discount:
                    discount = i.price_unit * (i.discount/100)
                    totalDiscount = totalDiscount + discount
        self.fe_total_descuento = totalDiscount


    def _compute_total_venta(self):
        _logger.info(f"DEF197 ===== _compute_total_venta")
        log.info('--> factelec/_compute_total_venta')
        for s in self:
            totalSale = 0
            for i in s.invoice_line_ids:
                totalAmount = i.price_unit * i.quantity
                totalSale = totalSale + totalAmount

        self.fe_total_venta = totalSale


    @api.depends("fe_total_mercancias_exentas")
    def _compute_total_mercancias_exentas(self):
        _logger.info(f"DEF210 ===== fe_total_mercancias_exentas")
        log.info('--> factelec/_compute_total_mercancias_exentas REPETIDO2')
        total_mercancias_exentas = 0
        for s in self:
            for i in s.invoice_line_ids:
                if i.product_id.type != 'Service':
                    #asking for tax for know if the product is exempt
                    if not i.tax_ids:
                        totalAmount = i.price_unit * i.quantity
                        total_mercancias_exentas = total_mercancias_exentas + totalAmount

        self.fe_total_mercancias_exentas = total_mercancias_exentas

    def _remove_sign(self,xml):
        _logger.info(f"DEF224 =====")
        log.info('--> factelec/_remove_sign')
        ds = "http://www.w3.org/2000/09/xmldsig#"
        xades = "http://uri.etsi.org/01903/v1.3.2#"

        root_xml = fromstring(base64.b64decode(xml))
        ns2 = {"ds": ds, "xades": xades}
        signature = root_xml.xpath("//ds:Signature", namespaces=ns2)[0]
        root_xml.remove(signature)
        return root_xml

    def convert_xml_to_dic(self, xml):
        _logger.info(f"DEF236 =====")
        log.info('--> factelec-Invoice-convert_xml_to_dic')
        dic = xmltodict.parse(base64.b64decode(xml))
        return dic

    def get_doc_type(self, dic):
        _logger.info(f"DEF242 =====")
        log.info('--> factelec/get_doc_type')
        tag_TE = 'https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.3/tiqueteElectronico'
        tag_FE = 'https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.3/facturaElectronica'
        tag_MH = 'https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.3/mensajeHacienda'
        try:
            if 'TiqueteElectronico' in dic.keys():
                if dic['TiqueteElectronico']['@xmlns'] == tag_TE:
                    return 'TE'
            elif 'FacturaElectronica' in dic.keys():
                if dic['FacturaElectronica']['@xmlns'] == tag_FE:
                    return 'FE'
            elif 'MensajeHacienda' in dic.keys():
                if dic['MensajeHacienda']['@xmlns'] == tag_MH:
                    return 'MH'
        except Exception as e:
            log.info('\n "error al obtener tipo de archivo xml %s"\n', e)
            return False

    @api.onchange("fe_xml_supplier_hacienda")
    def _onchange_xml_hacienda(self):
       _logger.info(f"DEF263 =====")
       #1569524732
       if self.fe_xml_supplier_hacienda:
           root_xml = self._remove_sign(self.fe_xml_supplier_hacienda)
           dic = self.convert_xml_to_dic(self.fe_xml_supplier_hacienda)
           if not dic.get("MensajeHacienda"):
               raise exceptions.UserError(("El xml de hacienda no es un archivo valido"))

    @api.onchange("fe_xml_supplier")
    def _onchange_xml_factura(self):
        _logger.info(f"DEF273 =====")
        #1569524296
        log.info('--> factelec/_onchange_field')
        if self.fe_xml_supplier:
            root_xml = self._remove_sign(self.fe_xml_supplier)
            dic = self.convert_xml_to_dic(self.fe_xml_supplier)
            if not dic.get("FacturaElectronica"):
                raise exceptions.UserError(("La factura xml no es un archivo de factura valido"))
            doc_type = self.get_doc_type(dic)
            # 1570054332
            self.fe_xml_supplier_xslt = self.transform_doc(root_xml,doc_type)
            self.update({'fe_clave' : dic['FacturaElectronica']['Clave']})
        else:
            return{
                'value': {
                            'fe_xml_supplier_xslt': None,
                            'fe_msg_type': None,
                            'fe_detail_msg':None,
                            'fe_clave':None,
                        }
            }


    def _cr_validate_mensaje_receptor(self):
        _logger.info(f"DEF297 =====")
        log.info('--> factelec-Invoice-_cr_validate_mensaje_receptor')
        #if self.state != 'open':  #Se cambio de 'open' a draft or cancel
        #if (self.state != 'open' and self.state != 'paid'):
        #   msg = 'La factura debe de estar en Open o Paid para poder confirmarse'
        #   raise exceptions.UserError((msg))
        if self.fe_msg_type == False:
            msg = 'Falta seleccionar el mensaje: Acepta, Acepta Parcial o Rechaza el documento'
            raise exceptions.UserError((msg))
        else:
            if self.fe_detail_msg == False and  self.fe_msg_type != '1':
                msg = 'Falta el detalle mensaje'
                raise exceptions.UserError((msg))


        log.info('===> XXXX VALIDACION QUE HAY ADJUNTO UN XML DEL EMISOR/PROVEEDOR')
        log.info('===> XXXX VALIDACION QUE EL XML ES DEL TIPO FacturaElectronica')


    def _cr_xml_mensaje_receptor(self):
        _logger.info(f"DEF317 =====")
        log.info('--> factelec-Invoice-_cr_xml_mensaje_receptor')

        bill_dic = self.convert_xml_to_dic(self.fe_xml_supplier)

        if 'FacturaElectronica' in bill_dic.keys():

            self.invoice = {self.fe_doc_type:{
                'Clave':bill_dic['FacturaElectronica']['Clave'],
                'NumeroCedulaEmisor':bill_dic['FacturaElectronica']['Emisor']['Identificacion']['Numero'],
                'TipoCedulaEmisor':bill_dic['FacturaElectronica']['Emisor']['Identificacion']['Tipo'],
                'FechaEmisionDoc':self.fe_fecha_emision_doc.split(' ')[0]+'T'+self.fe_fecha_emision_doc.split(' ')[1]+'-06:00',
                'Mensaje':self.fe_msg_type,
                'DetalleMensaje':self.fe_detail_msg,
                'CodigoActividad': self.fe_activity_code_id.code,
                'CondicionImpuesto':self.tax_condition,
                #PENDIENTE AGREGAR CAMPO 'MontoTotalImpuestoAcreditar':'PENDIENTE2 CALCULAR 0.00',
                #PENDIENTE AGREGAR CAMPO 'MontoTotalDeGastoAplicable':'PENDIENTE2 CALCULAR 0.00',
                'MontoTotalImpuesto':bill_dic['FacturaElectronica']['ResumenFactura']['TotalImpuesto'],
                'TotalFactura':bill_dic['FacturaElectronica']['ResumenFactura']['TotalComprobante'],
                'NumeroCedulaReceptor':self.company_id.vat.replace('-','').replace(' ','') or None,#bill_dic['FacturaElectronica']['Receptor']['Identificacion']['Numero'],
                'TipoCedulaReceptor':bill_dic['FacturaElectronica']['Receptor']['Identificacion']['Tipo'],
                'NumeroConsecutivoReceptor':self.name,
                #'EmisorEmail':self.partner_id.email,
                #'pdf':self._get_pdf_bill(self.id) or None,
                }}
            return self.invoice
        else:
            msg = 'adjunte una factura electronica antes de confirmar la aceptacion'
            raise exceptions.UserError((msg))

    def _cr_post_server_side(self):
        _logger.info(f"DEF349 =====")
        if not self.company_id.fe_certificate:
            raise exceptions.UserError(('No se encuentra el certificado en compañia'))
            
        log.info('--> factelec-Invoice-_cr_post_server_side')
        
        if self.name[8:10] == '05':
            self._cr_validate_mensaje_receptor()
            invoice = self._cr_xml_mensaje_receptor()
        else:
            invoice = self._cr_xml_factura_electronica()
        
        json_string = {
                      'invoice': invoice,
                      'certificate':base64.b64encode(self.company_id.fe_certificate).decode('utf-8'),
                      'token_user_name':self.company_id.fe_user_name,
                      }
        json_to_send = json.dumps(json_string)
        _logger.info(f"========== json to send : \n {json_to_send[:2000]} \n")

        header = {'Content-Type':'application/json'}
        url = self.company_id.fe_url_server
        try:
            response = requests.post(url, headers = header, data = json_to_send)
        except Exception as ex:
            if 'Name or service not known' in str(ex.args):
                raise ValidationError('Error al conectarse con el servidor! valide que sea un URL valido ya que el servidor no responde')
            else:
                 raise ValidationError(ex) 
        try:
           log.info('===335==== Response : \n  %s',response.text )
           '''Response : {"id": null, "jsonrpc": "2.0", "result": {"status": "200"}}'''
           json_response = json.loads(response.text)
           
           result = ""
           if "result" in json_response.keys():
               result = json_response['result']
               if "status" in result.keys():
                   if result['status'] == "200":
                       log.info('====== Exito \n')
                       self.update({'fe_server_state':'enviado a procesar'})

               elif "error" in  result.keys():
                    if self.name in str(result) and 'already exists' in str(result):
                        _logging.info(f"DEF349 {self.name} - Already Processed or Duplicated\n")
                        self.update({'fe_server_state':'enviado a procesar'})
                    else:
                        result = json_response['result']['error']
                        _logging.info(f"DEF353 {self.name} Error: {result}\n")
                        body = "Error "+result
                        self.write_chatter(body)
                        

        except Exception as e:
            body = "Error "+str(e)
            self.write_chatter(body)


    def confirm_bill(self):
        _logger.info(f"DEF406 ===== confirm_bill self: {self}")
        log.info('--> factelec-Invoice-confirm_bill')

        if not 'http://' in self.company_id.fe_url_server and  not 'https://' in self.company_id.fe_url_server:
            raise ValidationError("El campo Server URL en comapañia no tiene el formato correcto, asegurese que contenga http://")

        if self.state == 'draft':
           raise exceptions.UserError('VALIDE primero este documento')

        elif not self.fe_payment_type:
           raise exceptions.UserError('Seleccione el TIPO de PAGO')

        if self.fe_xml_hacienda:
           raise exceptions.UserError("Ya se tiene la RESPUESTA de Hacienda")

        country_code = self.company_id.partner_id.country_id.code

        self.source_date = self.invoice_date

        if country_code == 'CR':
            
            if self.name[8:10] == "01": 
                self._validate_company()
                self.validar_datos_factura()
                self._validate_invoice_line()                   #FACTURA ELECTRONICA
                self.fe_doc_type = "FacturaElectronica"
                self._cr_post_server_side()
                

            elif self.name[8:10] == "02":
                self._validate_company()
                self.validar_datos_factura()
                self._validate_invoice_line()                  #NOTA DEBITO ELECTRONICA
                self.fe_doc_type = "NotaDebitoElectronica"
                self._cr_post_server_side()

            elif self.name[8:10] == "03": 
                self._validate_company()
                self.validar_datos_factura()
                self._validate_invoice_line()                 #NOTA CREDITO ELECTRONICA
                self.fe_doc_type = "NotaCreditoElectronica"
                self._cr_post_server_side()
            
            elif self.name[8:10] == "04": 
                self._validate_company()
                self.validar_datos_factura()
                self._validate_invoice_line()                 #NOTA TIQUETE ELECTRONICO
                self.fe_doc_type = "TiqueteElectronico"
                self._cr_post_server_side()

            elif self.name[8:10] == "05":                 #Vendor Bill - Mensaje Receptor - Aceptar Factura

                if self.fe_xml_hacienda:
                   msg = '--> Ya se tiene el XML de Hacienda Almacenado'
                   log.info(msg)
                   raise exceptions.UserError((msg))

                else:
                   self.fe_doc_type = "MensajeReceptor"
                   tz = pytz.timezone('America/Costa_Rica')
                   self.fe_fecha_emision_doc = datetime.now(tz=tz).strftime("%Y-%m-%d %H:%M:%S")
                   self._cr_post_server_side()

            elif self.name[8:10] == "08":  
                self._validate_company()
                self.validar_datos_factura()
                self._validate_invoice_line()                  #FACTURA ELECTRONICA COMPRA
                self.fe_doc_type = "FacturaElectronicaCompra"
                self._cr_post_server_side()

            elif self.name[8:10] == "09":
                self._validate_company()
                self.validar_datos_factura()
                self._validate_invoice_line()                    #FACTURA ELECTRONICA COMPRA
                self.fe_doc_type = "FacturaElectronicaExportacion"
                self._cr_post_server_side()

    def transform_doc(self,root_xml,type):
        _logger.info(f"DEF475 =====")
        log.info('--> transform_doc')
        transform = None
        dom = ET.fromstring(tostring(root_xml,pretty_print=True))
        
        #filedir = os.path.dirname(os.path.realpath(__file__))
        #filepath = os.path.join(filedir, 'xslt/fe.xslt')
        ruta = path._path[0]+"/fe.xslt"
        if(type == 'FE'):
            transform = ET.XSLT(ET.parse(ruta))
        nuevodom = transform(dom)
        return ET.tostring(nuevodom, pretty_print=True)


    def _get_date(self, date):
       _logger.info(f"DEF490 =====")
       log.info('--> factelec/Invoice/_get_date')
       date_obj = datetime.strptime(date, "%Y-%m-%d")

       tm = pytz.timezone(self.env.user.tz or 'America/Costa_Rica')
       now_timezone  =  pytz.utc.localize(date_obj).astimezone(tm)
       date = now_timezone
       return date.strftime("%y-%m-%d").split('-')


    def _transform_date(self,date,tz):
        _logger.info(f"DEF501 =====")
        log.info('--> factelec-Invoice-_transform_date')
        new_date = ''
        if tz == "GMT":
             date_obj = datetime.strptime(date, "%Y-%m-%d %H:%M:%S")
             tm = pytz.timezone(self.env.user.tz or 'America/Costa_Rica')
             now_timezone  =  pytz.utc.localize(date_obj).astimezone(tm)
             new_date = now_timezone.isoformat('T')
        if tz == "UTC":
             new_date = datetime.strptime(date,"%Y-%m-%d %H:%M:%S").isoformat('T')+"Z"
        return new_date

    def _validate_company(self):
        _logger.info(f"DEF514 ===== _validate_company self: {self.name}")
        log.info('--> _validate_company')
        error = False
        msg = 'En Compania:\n'
        if not self.company_id.country_id:
            error = True
            msg += "El pais de la compañia es requerido.\n"

        if not self.company_id.fe_url_server:
            error = True
            msg += "Configure el URL del Servidor en Settings/User & Companies/ TAB: Factura Electronica -> URL\n"
        if not self.company_id.fe_activity_code_ids:
            error = True
            msg += "Falta agregar codigo de actividad en Settings/User & Companies/TAB: Factura Electronica\n"
        if error:
            raise exceptions.UserError((msg))

    def _validate_invoice_line(self):
        _logger.info(f"DEF532 =====")
        if len( self.name ) != 20:
            return
        units = ['Al', 'Alc', 'Cm', 'I', 'Os', 'Sp', 'Spe', 'St', 'd', 'm', 'kg', 's', 'A', 'K', 'mol', 'cd', 'm²', 'm³', 'm/s', 'm/s²', '1/m', 'kg/m³', 'A/m²', 'A/m', 'mol/m³', 'cd/m²', '1', 'rad', 'sr', 'Hz', 'N', 'Pa', 'J', 'W', 'C', 'V', 'F', 'Ω', 'S', 'Wb', 'T', 'H', '°C', 'lm', 'lx', 'Bq', 'Gy', 'Sv', 'kat', 'Pa·s', 'N·m', 'N/m', 'rad/s', 'rad/s²', 'W/m²', 'J/K', 'J/(kg·K)', 'J/kg', 'W/(m·K)', 'J/m³', 'V/m', 'C/m³', 'C/m²', 'F/m', 'H/m', 'J/mol', 'J/(mol·K)', 'C/kg', 'Gy/s', 'W/sr', 'W/(m²·sr)', 'kat/m³', 'min', 'h', 'd', 'º', '´', '´´', 'L', 't', 'Np', 'B', 'eV', 'u', 'ua', 'Unid', 'Gal', 'g', 'Km', 'Kw', 'ln', 'cm', 'mL', 'mm', 'Oz', 'Otros']
        service_units = ['Os','Sp','Spe','St','h']
        log.info('--> _validate_invoice_line')
        for line in self.invoice_line_ids:
            if len(line.name) > 200:
                raise exceptions.UserError(("La descripción del producto {0} no puede ser mayor a 200 caracteres".format(line.name)))
            if line.product_id:
                if line.product_id.type == 'service':
                    if line.product_uom_id.uom_mh not in service_units:
                        raise exceptions.UserError(("La unidad de medida {0} no corresponde a una unidad valida para un servicio ! configure el campo Unidad Medida MH en la Unidad {1}".format(line.product_uom_id.uom_mh,line.product_uom_id.name)))
                else: 
                    if line.product_uom_id.uom_mh not in units:
                        raise exceptions.UserError(("La unidad de medida {0} no corresponde a una unidad valida en el ministerio de hacienda! configure el campo Unidad Medida MH en la Unidad {1}".format(line.product_uom_id.uom_mh,line.product_uom_id.name)))   
            else:
                if line.product_uom_id.uom_mh not in units:
                        raise exceptions.UserError(("La unidad de medida {0} no corresponde a una unidad valida en el ministerio de hacienda! configure el campo Unidad Medida MH en la Unidad {1}".format(line.product_uom_id.uom_mh,line.product_uom_id.name)))   

            if not line.product_id.cabys_code_id:
                raise exceptions.UserError(("El producto {0} no contiene código CABYS".format(line.product_id.name)))


            if line.tax_ids:

               for tax_id in line.tax_ids:

                  if tax_id.type == 'OTHER':
                     if not tax_id.tipo_documento:
                        raise exceptions.UserError(("CONFIGURE el TIPO de DOCUMENTO de OTROS CARGOS  en Accounting/Configuration/Taxes"))
                        return
                  else:
                     if not tax_id.codigo_impuesto:
                        raise exceptions.UserError(("CONFIGURE el TIPO de IMPUESTO en Accounting/Configuration/Taxes"))
                        return

                     if not tax_id.tarifa_impuesto:
                        raise exceptions.UserError(("Configure la TARIFA de IMPUESTO en Accounting/Configuration/Taxes"))
                        return

           
    def validar_datos_factura(self):
            _logger.info(f"DEF541 ===== validar_datos_factura: {self.name}")
            if len( self.name ) != 20:
                return
            msg = ''
            #_logger.info(f"DEF545 {self.name} url: {self.company_id.fe_url_server}")
            doc_fields = [  'id', 'name', 'partner_id', 'state', 'move_type', 'ref',
                            'invoice_payment_term_id', 'country_code', 'currency_id',
                            'fe_clave', 'fe_doc_type', 'fe_payment_type', 'fe_receipt_status',
                            'fe_activity_code_id', 'fe_doc_ref', 'fe_tipo_documento_referencia',
                            'fe_informacion_referencia_codigo', 'fe_informacion_referencia_fecha',
                         ]
            data = self.search_read([
                ('id', '=', self.id)
            ],doc_fields)
            if len(data) != 1:
                raise ValidationError("Error: Multiple Records Found: {data}")
            else:
                data = data[0]
            
            data['partner_country_code'] = self.partner_id.country_id.code
            data['partner_state_fe_code'] = self.partner_id.state_id.fe_code
            data['partner_canton_fe_code'] = self.partner_id.canton_id.code
            data['partner_distrito_fe_code'] = self.partner_id.distrito_id.code
            data['partner_barrio_fe_code'] = self.partner_id.barrio_id.code
        
            _logger.info(f"DEF561 ===== {data}")
            
            url = f'{self.company_id.fe_url_server}'.replace('/api/v1/billing/','')
            url += '/api/v1/validate'
            
            header = { 'Content-Type': 'application/json', }
            response = requests.post(url,
                            headers = header,
                            data = json.dumps(data, default=str),
                            timeout=15)

            try:
                msg_errors = response.json().get('result').get('is_valid')
            except:
                raise ValidationError(f"Error Server-Side: \n{response.text}")
            
            if len(msg_errors) > 0:
                for msg_error in msg_errors:
                    msg += (msg_error + "\n")
            
            if self.name[8:10] != '08':
                if len(self.partner_id.country_id) == 0 or self.partner_id.country_id.code == "CR":
                    if self.partner_id.state_id:
                        if not self.partner_id.state_id.fe_code:
                            msg += 'En el Cliente, el codigo para factura electronica de la provincia es requerida \n'

                        if not self.partner_id.canton_id:
                            msg += 'En el Cliente, el canton es requerido \n'

                        if not self.partner_id.distrito_id:
                            msg += 'En el Cliente, el distrito es requerido \n'

                        if not self.partner_id.street:
                            msg += 'En el Cliente, el campo otras señas es requerido \n'

            if not self.fe_activity_code_id:
                msg += 'Falta la actividad económica \n'
            elif len(self.fe_activity_code_id.code) != 6:
                msg += 'El codigo de la actividad económica debe ser de un largo de 6 \n'
            
            if not self.invoice_payment_term_id.payment_term_hacienda:
                msg += 'En el plazo de pago falta el plazo credito hacienda \n'
            elif len(self.invoice_payment_term_id.payment_term_hacienda) > 10:
                msg += 'El nombre del plazo de pago debe ser menor aun largo de 10 \n'
                
            if not self.name:
                msg += 'El documento no contiene numero consecutivo \n'
            elif len(self.name) != 20:
                msg += 'El consecutivo del documento debe ser de un largo de 20 \n'
            
            if not self.fe_clave:
                msg += 'El documento no contiene clave \n'

            elif len(self.fe_clave) != 50:
                msg += 'La clave tiene que tener un largo de 50 \n'
            
            if not self.fe_fecha_emision:
                msg += 'Falta la fecha de emisión \n'
                
            if not self.invoice_payment_term_id.fe_condition_sale:
                msg += 'Falta definir en el plazo de pago la condición de venta\n'
            
            if not self.fe_payment_type:
                msg += 'Falta el tipo de pago \n'
                
            if not self.fe_receipt_status:
                msg += 'Falta la situación del comprobante \n'
            
            #if self.name[8:10] == '03' or self.name[8:10] == '02':
                #if not self.fe_doc_ref:
                #    msg += 'Falta el documento de referencia \n'
                #if not self.fe_tipo_documento_referencia:
                #    msg += 'Falta el tipo documento referencia \n'
                #if not self.fe_informacion_referencia_codigo:
                #    msg += 'Falta el codigo referencia \n'
                #if not self.ref:
                #    msg += 'Falta la razón en el campo referencia \n'
            
                
            if not self.company_id.company_registry:
                msg += 'En compañia, falta el campo registro de la compañia \n'
            
            if not self.company_id.fe_comercial_name:
                msg += 'En compañia, falta el campo nombre comercial \n'
            if not self.company_id.fe_identification_type:
                msg += 'En compañia, falta el tipo de identificación \n'
            if not self.company_id.vat:
                msg += 'En compañia, falta el campo NIF \n'
            elif len(self.company_id.vat) < 9 and len(self.company_id.vat) >12:
                msg += 'En compañia, el largo del NIF debe ser entre 9 y 12 \n'
                
                
             #Docuemento tipo 08 factura de proveedor regimen simplificado   
            if self.name[8:10] == '08':
                
                if not self.partner_id.state_id:
                     msg += 'En el proveedor, la provincia es requerida \n'
                
                elif not self.partner_id.state_id.fe_code:
                     msg += 'En el proveedor, el codigo para factura electronica de la provincia es requerida \n'

                if not self.partner_id.canton_id:
                    msg += 'En el proveedor, el canton es requerido \n'
                    
                if not self.partner_id.distrito_id:
                    msg += 'En el proveedor, el distrito es requerido \n'

                if not self.partner_id.street:
                    msg += 'En el proveedor, el campo otras señas es requerido \n'
                    
            
            
            if not self.company_id.state_id:
                 msg += 'En compañia, la provincia es requerida \n'
            elif not self.company_id.state_id.fe_code:
                 msg += 'En compañia, el codigo para factura electronica de la provincia es requerida \n'
                    
            if not self.company_id.canton_id:
                msg += 'En compañia, el canton es requerido \n'
                
            if not self.company_id.distrito_id:
                    msg += 'En compañia, el distrito es requerido \n'
            
            if not self.company_id.street:
                msg += 'En compañia, el campo otras señas es requerido \n'
            
            if not self.company_id.phone:
                msg += 'En compañia, falta el numero de teléfono \n'
            elif len(self.company_id.phone) < 8 and len(self.company_id.phone) > 20:
                 msg += 'En compañia, el numero de teléfono debe ser igual o mayor que 8 y menor que 20 \n'
            #elif not re.search('^\d+$',self.company_id.phone): #En otra parte se quitan los caracteres especiales
            #    msg += 'En compañia, el numero de teléfono debe contener solo numeros \n'
            
            if self.company_id.fe_fax_number:
                if len(self.company_id.fe_fax_number)  < 8 and len(self.company_id.fe_fax_number) > 20:
                    msg += 'En compañia, el numero de fax debe ser igual o mayor que 8 y menor que 20 \n'
            
            if not self.company_id.email:
                 msg += 'En compañia, el correo electronico es requerido \n'
            
            _logger.info(f"DEF710 name: {self.name}\n")
            
            if  self.name[8:10] not in ['03', '04', '09']:
            
                if not self.partner_id.fe_identification_type:
                    msg += 'En el cliente, falta el tipo de identificación \n'

                if not self.partner_id.vat:
                    msg += 'En el cliente, falta el campo NIF \n'
                
            elif len(self.company_id.vat) < 9 and len(self.company_id.vat) >12:
                msg += 'En el cliente, el largo del NIF debe ser entre 9 y 12 \n'
            
            if self.partner_id.phone:
                if len(self.partner_id.phone) < 8 and len(self.partner_id.phone) > 20:
                  msg += 'En el cliente, el numero de teléfono debe ser igual o mayor que 8 y menor que 20 \n'
            
            if self.partner_id.fe_fax_number:
                if len(self.partner_id.fe_fax_number)  < 8 and len(self.partner_id.fe_fax_number) > 20:
                   msg += 'En el cliente, el numero de fax debe ser igual o mayor que 8 y menor que 20 \n'
            
            if not self.partner_id.email and self.name[8:10] not in ['03', '04']:
                 msg += 'En el cliente, el correo electrónico es requerido \n'
            
            #_logger.info(f"DEF734 {self} - {self.name[8:10]}")
            #if self.name[8:10] in ['02', '03'] and self.fe_informacion_referencia_fecha == False:
            #    msg += 'La Fecha de información de referencia hace falta\n'
            
            if msg:
                self.write_chatter("Errores:\n" + msg)
                raise ValidationError("Errores:\n" + msg)

            
    
    def _generar_clave(self):
        _logger.info(f"DEF726 ===== _generar_clave self: {self} name: {self.name}\n")
        
        if len( self.name ) != 20:
            return
        
        document_date_invoice = datetime.strptime(str(self.invoice_date),'%Y-%m-%d')
        if self.fe_doc_type != "MensajeReceptor":
            country_code = self.company_id.country_id.phone_code
            vat = self.company_id.vat or ''
            vat = vat.replace('-','')
            vat = vat.replace(' ','')
            vat_complete = "0" * (12 - len(vat)) + vat
            epoch = str( datetime.utcnow().timestamp() )[2:10]
            clave = str(country_code) + document_date_invoice.strftime("%d%m%y") \
                + str(vat_complete) + str(self.name) + str(self.fe_receipt_status or '1') \
                + str(epoch)
        self.fe_clave = clave
    
    def action_post(self,validate = True):
        _logger.info(f"DEF743a ===== action_post self: {self} fe_invoice_type: {self.fe_doc_type} validate: {validate}\n")
        _logger.info(f"DEF743b ===== move_type: {self.move_type}")
        for s in self:
            log.info('--> action_post')
            _logger.info(f"DEF746 ===== action_post self: {s} fe_invoice_type: {s.fe_doc_type} fe_msg_type: {s.fe_msg_type}\n    Name: {s.name}\n")
            #_logger.info(f"DEF747 ===== journal_id: {dir(s.journal_id)}\n")
            _logger.info(f"DEF747 ===== journal_id refund_sequence: {s.journal_id.refund_sequence}\n")
            
            _logger.info(f"DEF772 ===== sequence_number: {s.sequence_number} - sequence_prefix: {s.sequence_prefix}")
            
            if s.company_id.country_id.code != 'CR' or s.fe_doc_type == False or validate == False or s.move_type == 'entry':
                _logger.info(f"DEF748a Not Electronic Invoice or validate False =============\n sequence_fe: {s.journal_id.sequence_fe}\n")
                _logger.info(f"DEF748b Not Electronic Invoice or validate False =============\n sequence_nd: {s.journal_id.sequence_nd}\n")
                _logger.info(f"DEF748c Not Electronic Invoice or validate False =============\n fe_doc_type: {s.fe_doc_type}\n")
                _logger.info(f"DEF748c {s.move_type} fe_doc_type: {s.fe_doc_type}\n")
                
                if s.fe_doc_type == False and ( len(s.journal_id.sequence_fe) != 0 or len(s.journal_id.sequence_nd) != 0):
                    msg = f'Error: El diario "{s.journal_id.name}" es solo para Documentos Electrónicos'
                    msg = msg + f"\nSeleccione el tipo de documento correspondiente"
                    msg = msg + f"\nEn caso de ser necesario, vaya a Diarios y configure un nuevo diario"
                    raise ValidationError(msg)
                
                res = super(AccountMoveFunctions, s).action_post()
                return res
        
            elif s.move_type == "out_invoice" and s.fe_doc_type in ["NotaCreditoElectronica", "MensajeReceptor", "FacturaElectronicaCompra"]:
                msg = f'Error: El Tipo de Documento: {s.fe_doc_type} no es válido'
                raise ValidationError(msg)
            
            if s.company_id.country_id.code == 'CR' and s.fe_doc_type != False:
                
                if validate:
                    if s.fe_msg_type != '3':
                        log.info('--> 1570130084')
                        '''
                        for item in s.invoice_line_ids:
                            
                            if item.price_subtotal == False:
                                _logger.info(f"DEF799 {item} {item.price_subtotal}")
                                return {
                                        'type': 'ir.actions.act_window',
                                        'name': '¡Alerta!',
                                        'res_model': 'confirm.message',
                                        'view_type': 'form',
                                        'view_mode': 'form',
                                        'views': [(False, 'form')],
                                        'target': 'new',
                                        'context': {'invoice': s.id}
                                }
                        '''
                        #es mensaje de aceptacion??
                        #_logger.info(f"DEF771 sequence: {s.journal_id.sequence}")
                        
                        if s.fe_doc_type == "FacturaElectronica":
                            sequence = s.journal_id.sequence_fe
                        elif s.fe_doc_type == "NotaDebitoElectronica":
                            sequence = s.journal_id.sequence_nd
                        elif s.fe_doc_type == "NotaCreditoElectronica":
                            sequence = s.journal_id.sequence_nc
                        elif s.fe_doc_type == "TiqueteElectronico":
                            sequence = s.journal_id.sequence_te
                        elif s.fe_doc_type == "FacturaElectronicaExportacion":
                            sequence = s.journal_id.sequence_fee
                        elif s.fe_doc_type == "FacturaElectronicaCompra":
                            sequence = s.journal_id.sequence_fec
                        else:
                            sequence = False
                        
                        _logger.info(f"DEF788 sequence: {s.name}")
                        
                        if sequence == False:
                            msg = f'Falta configurar el número consecutivo en el diario/journal: {s.journal_id.name} para {s.fe_doc_type}'
                            raise exceptions.UserError((msg))                         
                        elif sequence.prefix == False:
                            msg = f'Falta configurar el prefijo en la secuencia: {sequence.name} para {s.fe_doc_type}'
                            raise exceptions.UserError((msg))
                        elif len(sequence.prefix) >= 10:
                            
                            _logger.info(f"DEF811 sequence: {sequence} / sequence_name: {sequence.name}")
                            _logger.info(f"DEF812 prefix: {sequence.prefix}")
                            
                            if sequence.prefix[8:10] == '05':
                                    if s.fe_xml_supplier == False:
                                        msg = 'Falta el XML del proveedor'
                                        raise exceptions.UserError((msg))
                                    if s.fe_msg_type == False:
                                        msg = 'Falta seleccionar el mensaje: Acepta, Acepta Parcial o Rechaza el documento'
                                        raise exceptions.UserError((msg))

                                    bill_dic = s.convert_xml_to_dic(s.fe_xml_supplier)
                                    total = bill_dic['FacturaElectronica']['ResumenFactura']['TotalComprobante']
                                    if float(total) != s.amount_total:
                                        return {
                                            'type': 'ir.actions.act_window',
                                            'name': '¡Alerta!',
                                            'res_model': 'confirm.alert',
                                            'view_type': 'form',
                                            'view_mode': 'form',
                                            'views': [(False, 'form')],
                                            'target': 'new',
                                            'context': {'invoice': s.id}
                                        }
                    else:

                        if s.fe_msg_type == False:
                            msg = 'Falta seleccionar el mensaje: Acepta, Acepta Parcial o Rechaza el documento'
                            raise exceptions.UserError((msg))
                        else:
                            if s.fe_detail_msg == False and  s.fe_msg_type != '1':
                                msg = 'Falta el detalle mensaje'
                                raise exceptions.UserError((msg))
                            if s.fe_msg_type == '3':
                                if s.amount_total > 0:
                                    raise exceptions.UserError('Esta factura fue rechazada, por lo tanto su total no puede ser mayor a cero')
                
                #if s.fe_doc_type in ['NotaDebitoElectronica', 'NotaCreditoElectronica'] and s.fe_informacion_referencia_fecha == False:
                #    raise ValidationError(f'  Error: Fecha de Información de Referencia está pendiente')
                    
                date_temp = s.invoice_date 
                log.info('--> 1575061615')
                _logger.info(f"DEF829 before action post=== res.name: {s.name}\n\n")
                
                activity_codes = self.env['activity.code'].search([('company_id', '=', s.company_id.id)])
                _logger.info(f"DEF820: company_id: self.company_id: {s.company_id} - activties codes: {activity_codes}")
                if len(activity_codes) == 1:
                    s.fe_activity_code_id = activity_codes.id
                
                _logger.info(f"DEF820: s.fe_activity_code_id: {s.fe_activity_code_id}")

                if s.name in ["", "/", False]:
                    
                    s.name = sequence._next_do()
                
                _logger.info(f"DEF836 after action post=== res.name: {s.name} prefix: {s.sequence_prefix}")
                
                res = super(AccountMoveFunctions, s).action_post()
                
                s.write({ 'sequence_prefix': sequence._get_prefix_suffix()[0]  })
                
                _logger.info(f"DEF838 after action post=== res.name: {s.name} prefix: {s.sequence_prefix}")
                
                tz = pytz.timezone('America/Costa_Rica')
                
                if not date_temp:
                    s.fe_fecha_emision = datetime.now(tz=tz).strftime("%Y-%m-%d %H:%M:%S")
                    s.invoice_date = s.fe_fecha_emision
                else:
                    s.fe_fecha_emision = '{0} {1}'.format(date_temp,datetime.now(tz=tz).strftime("%H:%M:%S"))
                
                s._validate_company()
                if s.name[8:10] != '05':
                    if s.fe_clave in [False, None, ""]:
                        _logger.info(f"DEF912 Generating fe_clave")
                        s._generar_clave()
                    
                log.info('--->Clave %s',s.fe_clave)
                
                s.validar_datos_factura()
                #s.validacion()
                s._validate_invoice_line()
                _logger.info(f"DEF844 res.name: {s.name} {s.sequence_prefix}")
            else:
                log.info('--> 1575061637')
                res = super(AccountMoveFunctions, s).action_post()

            _logger.info(f"DEF865 s.name: {s.name} {s.sequence_prefix}")

        
            _logger.info(f"DEF868 s.name: {s.name}")

                
    def get_invoice(self):
        _logger.info(f"DEF872 =====")
        for s in self:
            if not s.fe_server_state:
                raise exceptions.UserError('Porfavor envie el documento antes de consultarlo')
            if s.state == 'draft':
              raise exceptions.UserError('VALIDE primero este documento')
            #peticion al servidor a partir de la clave
            log.info('--> 1569447129')
            log.info(f'--> get_invoice: {s.name}')
            if not 'http://' in s.company_id.fe_url_server and  not 'https://' in s.company_id.fe_url_server:
               raise ValidationError("El campo Server URL en comapañia no tiene el formato correcto, asegurese que contenga http://")

            if s.name[8:10] == "05":
               if not s.fe_clave:
                  log.info("soy un documento 05 sin clave {}".format(s.name))
               url = s.company_id.fe_url_server+'{0}'.format(s.fe_clave+'-'+s.name)
            else:
               url = s.company_id.fe_url_server+'{0}'.format(s.fe_clave)

            header = {'Content-Type':'application/json'}
            
            try:
                r = requests.get(url, headers = header, data=json.dumps({}))
            except Exception as ex:
                _logger.info(f"Error al conectarse url: {url}")
                if 'Name or service not known' in str(ex.args):
                    raise ValidationError('Error al conectarse con el servidor! valide que sea un URL valido ya que el servidor no responde')
                else:
                    raise ValidationError(ex) 

            data = r.json()
            log.info('-->1569447795 result')
            
            #alamacena la informacion suministrada por el servidor
            if data.get('result'):

                if data.get('result').get('error'):
                   s.write_chatter(data['result']['error'])
                else:
                   params = {}
                   
                   if s.fe_server_state != data['result']['ind-estado']:
                       params['fe_server_state'] = data['result']['ind-estado']

                   if s.fe_name_xml_sign in [None, False, ""]:
                      params['fe_name_xml_sign'] = data['result']['nombre_xml_firmado']
                      params['fe_xml_sign'] = data['result']['xml_firmado']
                   
                   if s.fe_name_xml_hacienda in [None, False, ""]:
                      params['fe_name_xml_hacienda'] = data['result']['nombre_xml_hacienda']
                      params['fe_xml_hacienda'] = data['result']['xml_hacienda']
                   
                   if len(params) == 0:
                      msg = f"  Nothing FE value to Update in Record: {s.name}"
                      _logger.info( msg )
                      raise ValidationError( msg )
                   else:
                      s.update(params)
                
                
    def _get_pdf_bill(self,id):
        _logger.info(f"DEF877 ===== _get_pdf_bill self: {self} id: {id}")
        log.info('--> _get_pdf_bill')
        ctx = self.env.context.copy()
        ctx.pop('default_move_type', False)
        _logger.info(f"DEF938 ctx: {ctx}")
        #pdf = self.env.ref('account.account_invoices_without_payment').with_context(ctx).render(id)
        #pdf = self.env.ref('account.account_invoices').with_context(ctx).render(id) # Version 13
        pdf = self.env.ref('account.account_invoices').with_context(ctx)._render( 'account.account_invoices', [id] )
        pdf64 = base64.b64encode(pdf[0]).decode('utf-8')
        return pdf64


    @api.model
    def cron_get_server_bills(self):
        _logger.info(f"DEF889 ===== cron_get_server_bills self: {self}")
        log.info('--> cron_get_server_bills')
        list = self.env['account.move'].search(['|',('fe_xml_sign','=',False),('fe_xml_hacienda','=',False),'&',('state','=','posted'),
        ('fe_server_state','!=','pendiente enviar'),('fe_server_state','!=','error'),('fe_server_state','!=','Importada Manual'),('fe_server_state','!=',False),
        ('type','!=','entry')])

        for item in list:
            if item.company_id.country_id.code == 'CR' and item.fe_in_invoice_type != 'OTRO' and item.journal_id.type == 'sale':
                if item.fe_clave:
                    log.info(' item name %s',item.name)
                    item.get_invoice()
                else:
                    log.info(' item name no tiene clave %s',item.name)

               

    def write_chatter(self,body):
        _logger.info(f"DEF906 =====")
        log.info('--> write_chatter')
        chatter = self.env['mail.message']
        chatter.create({
                        'res_id': self.id,
                        'model':'account.move',
                        'body': body,
                       })


    def _cr_xml_factura_electronica(self):
        _logger.info(f"DEF974 ===== self: {self}")
        log.info('--> factelec-Invoice-_cr_xml_factura_electronica')
        for s in self:
            #changed s.invoice to invoice_data
            invoice_data = {}
            
            invoice_data[s.fe_doc_type] = {'CodigoActividad':s.fe_activity_code_id.code}
            invoice_data[s.fe_doc_type].update({'Clave':s.fe_clave})
            invoice_data[s.fe_doc_type].update({'NumeroConsecutivo':s.name})
            invoice_data[s.fe_doc_type].update({'FechaEmision':s.fe_fecha_emision.split(' ')[0]+'T'+s.fe_fecha_emision.split(' ')[1]+'-06:00'})
            invoice_data[s.fe_doc_type].update({'Emisor':{
                'Nombre':s.company_id.company_registry
            }})
            invoice_data[s.fe_doc_type]['Emisor'].update({
            'Identificacion':{
                'Tipo': s.company_id.fe_identification_type or None,
                'Numero':s.company_id.vat.replace('-','').replace(' ','') or None,
            },
            })
            
            if s.company_id.fe_comercial_name:
                invoice_data[s.fe_doc_type]['Emisor'].update({'NombreComercial':s.company_id.fe_comercial_name})
            
            invoice_data[s.fe_doc_type]['Emisor'].update({'Ubicacion':{
            'Provincia':s.company_id.state_id.fe_code,
            'Canton':s.company_id.canton_id.code,
            'Distrito':s.company_id.distrito_id.code,
            }})

            if s.company_id.barrio_id.code:
                invoice_data[s.fe_doc_type]['Emisor']['Ubicacion'].update({'Barrio':s.company_id.barrio_id.code})

            invoice_data[s.fe_doc_type]['Emisor']['Ubicacion'].update({'OtrasSenas':s.company_id.street})

            if s.company_id.phone:
                invoice_data[s.fe_doc_type]['Emisor'].update({'Telefono':{
                    'CodigoPais':str(s.company_id.country_id.phone_code),
                    'NumTelefono':s.company_id.phone.replace('-','').replace(' ','').replace('+506','').replace('+',''),
                }})
            if s.env.user.company_id.fe_fax_number:
                invoice_data[s.fe_doc_type]['Emisor'].update({'Fax':{
                    'CodigoPais':str(s.company_id.country_id.phone_code),
                    'NumTelefono':s.company_id.fe_fax_number.replace('-','').replace(' ','').replace('+506','').replace('+',''),
                }})

            invoice_data[s.fe_doc_type]['Emisor'].update({'CorreoElectronico':s.company_id.email})

            invoice_data[s.fe_doc_type].update({'Receptor':{
            'Nombre':s.partner_id.name,
            }})

            if s.partner_id.vat:
                invoice_data[s.fe_doc_type]['Receptor'].update({'Identificacion':{
                    'Tipo':s.partner_id.fe_identification_type,
                    'Numero':s.partner_id.vat.replace('-','').replace(' ','') or None,
                }})

            if s.partner_id.fe_receptor_identificacion_extranjero:
                invoice_data[s.fe_doc_type]['Receptor'].update({'IdentificacionExtranjero':s.partner_id.fe_receptor_identificacion_extranjero})

            if s.partner_id.fe_comercial_name:
                invoice_data[s.fe_doc_type]['Receptor'].update({'NombreComercial':s.partner_id.fe_comercial_name})

            if s.partner_id.state_id.fe_code:
                invoice_data[s.fe_doc_type]['Receptor'].update({'Ubicacion':{
                    'Provincia':s.partner_id.state_id.fe_code or '',
                    'Canton':s.partner_id.canton_id.code or '',
                    'Distrito':s.partner_id.distrito_id.code or '',
                    'OtrasSenas':s.partner_id.street or '',
                }})

            if  s.partner_id.state_id.fe_code and s.partner_id.barrio_id.code:
                invoice_data[s.fe_doc_type]['Receptor']['Ubicacion'].update({'Barrio':s.partner_id.barrio_id.code})

            #if s.partner_id.fe_receptor_otras_senas_extranjero:
            #   invoice_data[s.fe_doc_type]['Receptor'].update({'OtrasSenasExtranjero':s.partner_id.fe_receptor_otras_senas_extranjero})

            if s.partner_id.phone:
                invoice_data[s.fe_doc_type]['Receptor'].update({'Telefono':{
                    'CodigoPais':str(s.company_id.country_id.phone_code),
                    'NumTelefono':s.partner_id.phone.replace('-','').replace(' ','').replace('+506','').replace('+','') or None,
                }})

            if s.partner_id.fe_fax_number:
                invoice_data[s.fe_doc_type]['Receptor'].update({'Fax':{
                    'CodigoPais':str(s.company_id.country_id.phone_code),
                    'NumTelefono':s.partner_id.fe_fax_number.replace('-','').replace(' ','').replace('+506','').replace('+',''),
                }})

            if s.partner_id.email:
                invoice_data[s.fe_doc_type]['Receptor'].update({'CorreoElectronico':s.partner_id.email})

            invoice_data[s.fe_doc_type].update({'CondicionVenta':s.invoice_payment_term_id.fe_condition_sale})

            if s.invoice_payment_term_id.payment_term_hacienda:
                invoice_data[s.fe_doc_type].update({'PlazoCredito':s.invoice_payment_term_id.payment_term_hacienda})
            if s.fe_condicion_impuesto:
                invoice_data[s.fe_doc_type].update({'CondicionImpuesto':s.fe_condicion_impuesto})
            
            invoice_data[s.fe_doc_type].update({'MedioPago':s.fe_payment_type})
            
            if s.fe_msg_type:
                invoice_data[s.fe_doc_type].update({'Mensaje':s.fe_msg_type})
                if s.fe_detail_msg:
                    invoice_data[s.fe_doc_type].update({'DetalleMensaje':s.fe_detail_msg})

            inv_lines = []
            OtrosCargos_array = []
            NumeroLinea = 1
            arrayCount = 0
            totalSale = 0
            TotalDescuentos = 0
            TotalServGravados = 0
            TotalServExentos = 0
            TotalServExonerado = 0
            TotalGravado = 0
            TotalMercanciasGravadas = 0
            TotalMercanciasExentas = 0
            TotalMercExonerada = 0
            TotalImpuesto = 0
            TotalOtrosCargos = 0
            OtrosCargos_array = []

            for i in s.invoice_line_ids:
                LineaCantidad = 0
                LineaImpuestoTarifa = 0
                LineaMontoDescuento = 0
                MontoTotalLinea = 0
                LineaImpuestoNeto = 0
                MontoExoneracion = 0
                percent = 0

                inv_lines.append({'NumeroLinea':NumeroLinea})

                #PartidaArancelaria   #PENDIENTE, Cuando el comprobante es del tipo Exportacion

                #if i.product_id.default_code:
                inv_lines[arrayCount]['Codigo'] = i.product_id.cabys_code_id.code

                if i.product_id.fe_codigo_comercial_codigo:
                    inv_lines[arrayCount]['CodigoComercial'] = {
                        'Tipo':i.product_id.fe_codigo_comercial_tipo,
                        'Codigo':i.product_id.fe_codigo_comercial_codigo,
                    }

                LineaCantidad = round(i.quantity,3)
                inv_lines[arrayCount]['Cantidad'] = '{0:.3f}'.format(LineaCantidad)

                inv_lines[arrayCount]['UnidadMedida'] = i.product_uom_id.uom_mh

                if i.product_id.fe_unidad_medida_comercial:
                    inv_lines[arrayCount]['UnidadMedidaComercial'] = i.product_id.fe_unidad_medida_comercial

                if i.name:
                    inv_lines[arrayCount]['Detalle'] = i.name or None

                LineaPrecioUnitario = round(i.price_unit,5)
                inv_lines[arrayCount]['PrecioUnitario'] = '{0:.5f}'.format(LineaPrecioUnitario)

                LineaMontoTotal = round((LineaCantidad * LineaPrecioUnitario),5)
                inv_lines[arrayCount]['MontoTotal'] = '{0:.5f}'.format(LineaMontoTotal)

                if i.discount:
                    LineaMontoDescuento = round((LineaMontoTotal * (i.discount/100)),5)
                    LineaNaturalezaDescuento = "Se aplica %s porciento de descuento" % (i.discount,)

                    inv_lines[arrayCount]['Descuento'] ={
                    'MontoDescuento':'{0:.5f}'.format(LineaMontoDescuento),
                    'NaturalezaDescuento':LineaNaturalezaDescuento[:80]
                    }
                    TotalDescuentos = round((TotalDescuentos + LineaMontoDescuento),5)

                LineaSubTotal = round((LineaMontoTotal - LineaMontoDescuento),5)
                inv_lines[arrayCount]['SubTotal'] = '{0:.5f}'.format(LineaSubTotal)

                if i.tax_ids:

                    ## COMIENZA TAXES y OTROS CARGOS

                    for tax_id in i.tax_ids :
                        MontoCargo = 0
                        LineaImpuestoMonto = 0

                        if tax_id.type == 'OTHER': #

                            OtrosCargos_json = { 'TipoDocumento':tax_id.tipo_documento }

                            OtrosCargos_json.update({'Detalle':tax_id.name})

                            OtrosCargos_json.update({'Porcentaje':'{0:.5f}'.format(tax_id.amount)})

                            MontoCargo = LineaMontoTotal * (tax_id.amount/100)

                            OtrosCargos_json.update({'MontoCargo':'{0:.5f}'.format(MontoCargo)})

                            OtrosCargos_array.append(OtrosCargos_json)

                            TotalOtrosCargos += MontoCargo

                        else:
                            
                            if self.fiscal_position_id:
                                old_tax = self.fiscal_position_id.tax_ids.search([('tax_dest_id','=',tax_id.id)]).tax_src_id
                                LineaImpuestoTarifa = round(old_tax.amount,2)
                                inv_lines[arrayCount]['Impuesto'] = {
                                    'Codigo':old_tax.codigo_impuesto,
                                    'CodigoTarifa':old_tax.tarifa_impuesto,
                                    'Tarifa':'{0:.2f}'.format(LineaImpuestoTarifa)
                                    }
                            else:
                                LineaImpuestoTarifa = round(tax_id.amount,2)
                                inv_lines[arrayCount]['Impuesto'] = {
                                    'Codigo':tax_id.codigo_impuesto,
                                    'CodigoTarifa':tax_id.tarifa_impuesto,
                                    'Tarifa':'{0:.2f}'.format(LineaImpuestoTarifa)
                                    }

                            LineaImpuestoMonto = round((LineaSubTotal * LineaImpuestoTarifa/100),5)
                            inv_lines[arrayCount]['Impuesto'].update(dict({'Monto':'{0:.5f}'.format(LineaImpuestoMonto)}))

                            if self.fiscal_position_id:
                                fiscal = self.fiscal_position_id.tax_ids.search([('tax_dest_id','=',tax_id.id)])
                                percent = fiscal.tax_src_id.amount - fiscal.tax_dest_id.amount
                                exoneration = {}
                                exoneration['TipoDocumento'] = self.fiscal_position_id.fiscal_position_type or ''
                                exoneration['NumeroDocumento'] = self.fiscal_position_id.document_number or ''
                                exoneration['NombreInstitucion'] = self.fiscal_position_id.institution_name or ''
                                exoneration['FechaEmision'] = self.fiscal_position_id.issued_date.strftime("%Y-%m-%dT%H:%M:%S-06:00") or ''
                                exoneration['PorcentajeExoneracion'] =  int(percent) or '0'
                                MontoExoneracion = round(LineaSubTotal * ( percent / 100),5)
                                exoneration['MontoExoneracion'] =  MontoExoneracion
                                inv_lines[arrayCount]['Impuesto'].update( dict({'Exoneracion': exoneration }) )
                                
                                if percent == 0 and LineaImpuestoTarifa == 0:
                                    percent = 1
                                    LineaImpuestoTarifa = 1
                                    
                                if i.product_id.type == 'service':
                                    TotalServExonerado = TotalServExonerado + LineaSubTotal * ( percent / LineaImpuestoTarifa )
                                else:
                                    TotalMercExonerada = TotalMercExonerada + LineaSubTotal * ( percent / LineaImpuestoTarifa )

                                

   
                            LineaImpuestoNeto = round(LineaImpuestoMonto - MontoExoneracion,5) # - LineaImpuestoExoneracion
                            inv_lines[arrayCount]['ImpuestoNeto'] = '{0:.5f}'.format(round(LineaImpuestoNeto,5))
                        #Si esta exonerado al 100% se debe colocar 0-Zero

                    #XXXXXX FALTA TOTAL IVA DEVUELTO

                            TotalImpuesto = round((TotalImpuesto + LineaImpuestoNeto),5)

                MontoTotalLinea = round((LineaSubTotal + LineaImpuestoNeto),5)
                inv_lines[arrayCount]['MontoTotalLinea'] = '{0:.5f}'.format(MontoTotalLinea)

                if i.product_id.type == 'service':
                    #asking for tax for know if the product is Tax Free
                    if i.tax_ids:
                        if self.fiscal_position_id:
                            TotalServGravados = TotalServGravados + (1-percent/LineaImpuestoTarifa) * LineaMontoTotal
                        else:
                            TotalServGravados = TotalServGravados + LineaMontoTotal
                    else:
                        TotalServExentos = TotalServExentos + LineaMontoTotal
                    #  XXXX PENDIENTE LOS ServExonerados
                else:
                    if i.tax_ids:
                         if self.fiscal_position_id:
                            TotalMercanciasGravadas = TotalMercanciasGravadas + (1-percent/LineaImpuestoTarifa) * LineaMontoTotal
                         else:
                            TotalMercanciasGravadas = TotalMercanciasGravadas + LineaMontoTotal #LineaSubTotal
                    else:
                        TotalMercanciasExentas = TotalMercanciasExentas + LineaMontoTotal #LineaSubTotal
                    #   XXXX PENDIENTE LOS MercanciasExoneradas


                NumeroLinea = NumeroLinea + 1
                arrayCount = arrayCount + 1

            invoice_data[s.fe_doc_type]['DetalleServicio'] = {'LineaDetalle':inv_lines}



            invoice_data[s.fe_doc_type].update({
            'OtrosCargos':OtrosCargos_array
            })

            invoice_data[s.fe_doc_type].update(
                {'ResumenFactura':{
                    'CodigoTipoMoneda':{
                        'CodigoMoneda':s.currency_id.name,
                        'TipoCambio':s.fe_currency_rate, #'{0:.2f}'.format((s.fe_currency_rate) or None),
                    }
                }})

            TotalGravado = TotalServGravados + TotalMercanciasGravadas
            TotalExento = TotalServExentos + TotalMercanciasExentas
            TotalExonerado = TotalServExonerado + TotalMercExonerada
            TotalVenta = TotalGravado + TotalExento + TotalExonerado   #REVISAR EL EXONERADO SI SE SUMA O RESTA
            TotalVentaNeta = TotalVenta - TotalDescuentos

            if TotalServGravados:
                invoice_data[s.fe_doc_type]['ResumenFactura'].update({'TotalServGravados':'{0:.5f}'.format(TotalServGravados)})

            if TotalServExentos:
                invoice_data[s.fe_doc_type]['ResumenFactura'].update({'TotalServExentos':'{0:.5f}'.format(TotalServExentos)})

            if TotalServExonerado:
                invoice_data[s.fe_doc_type]['ResumenFactura'].update({'TotalServExonerado':'{0:.5f}'.format(TotalServExonerado)})

            if TotalMercanciasGravadas:
                invoice_data[s.fe_doc_type]['ResumenFactura'].update({'TotalMercanciasGravadas':'{0:.5f}'.format(TotalMercanciasGravadas)})

            if TotalMercanciasExentas:
                invoice_data[s.fe_doc_type]['ResumenFactura'].update({'TotalMercanciasExentas':'{0:.5f}'.format(TotalMercanciasExentas)})

            if TotalMercExonerada:
                invoice_data[s.fe_doc_type]['ResumenFactura'].update({'TotalMercExonerada':'{0:.5f}'.format(TotalMercExonerada)})

            if TotalGravado:
                invoice_data[s.fe_doc_type]['ResumenFactura'].update({'TotalGravado':'{0:.5f}'.format(TotalServGravados + TotalMercanciasGravadas)})
            else:
                invoice_data[s.fe_doc_type]['ResumenFactura'].update({'TotalGravado':'0'})

            if TotalExento:
                invoice_data[s.fe_doc_type]['ResumenFactura'].update({'TotalExento':'{0:.5f}'.format(TotalServExentos + TotalMercanciasExentas)})

            if TotalExonerado:
                invoice_data[s.fe_doc_type]['ResumenFactura'].update({'TotalExonerado':'{0:.5f}'.format(TotalServExonerado + TotalMercExonerada)})

            if TotalVenta:
                invoice_data[s.fe_doc_type]['ResumenFactura'].update({'TotalVenta':'{0:.5f}'.format(TotalVenta)})
            else:
                invoice_data[s.fe_doc_type]['ResumenFactura'].update({'TotalVenta':'0'})

            if TotalDescuentos:
                invoice_data[s.fe_doc_type]['ResumenFactura'].update({'TotalDescuentos':'{0:.5f}'.format(TotalDescuentos)})

            if TotalVentaNeta:
                invoice_data[s.fe_doc_type]['ResumenFactura'].update({'TotalVentaNeta':'{0:.5f}'.format(TotalVentaNeta)})
            else:
                invoice_data[s.fe_doc_type]['ResumenFactura'].update({'TotalVentaNeta':'0'})

            if TotalImpuesto:
                invoice_data[s.fe_doc_type]['ResumenFactura']['TotalImpuesto'] = '{0:.5f}'.format(TotalImpuesto)
            else:
                invoice_data[s.fe_doc_type]['ResumenFactura']['TotalImpuesto'] = '0'



            ##PENDINETE TOTALIVADEVUELTO
            #self.invoice[self.fe_doc_type]['ResumenFactura']['TotalIVADevuelto'] = 'PENDIENTE_TOTAL_IVA_DEVUELTO'     # CONDICIONAL
                #Este campo será de condición obligatoria cuando se facturen servicios de salud y cuyo método de pago sea “Tarjeta”.
                #Se obtiene de la sumatoria del Monto de los Impuestos pagado por los servicios de salud en tarjetas.
                #Es un número decimal compuesto por 13 enteros y 5 decimales.

            if TotalOtrosCargos:
                invoice_data[s.fe_doc_type]['ResumenFactura']['TotalOtrosCargos'] = '{0:.5f}'.format(TotalOtrosCargos)

            TotalComprobante = TotalVentaNeta + TotalImpuesto #+ TotalOtrosCargos - TotalIVADevuelto
            if TotalComprobante:
                invoice_data[s.fe_doc_type]['ResumenFactura']['TotalComprobante'] = '{0:.5f}'.format(TotalComprobante) #'PENDIENTE_TOTAL_Comprobante'
            #SUMA DE: "total venta neta" + "monto total del impuesto" + "total otros cargos" - total IVA devuelto
            else:
                invoice_data[s.fe_doc_type]['ResumenFactura']['TotalComprobante'] ='0'

            if s.name[8:10] == "02" or s.name[8:10] == "03" or  s.name[8:10] == "08":
                if not s.fe_doc_ref:
                    error = True
                    msg = 'Indique el NUMERO CONSECUTIVO de REFERENCIA\n'
                else:
                    if len(s.fe_doc_ref) == 20:
                        origin_doc = s.search([('name', '=', s.fe_doc_ref)])
                        if origin_doc:
                            origin_doc_fe_fecha_emision = s.fe_informacion_referencia_fecha.astimezone( pytz.timezone('America/Costa_Rica') ).isoformat('T')
                            
                            invoice_data[s.fe_doc_type].update({
                                'InformacionReferencia':{
                                'TipoDoc':s.fe_tipo_documento_referencia,
                                'Numero':origin_doc.name,
                                'FechaEmision': origin_doc_fe_fecha_emision,
                                'Codigo':s.fe_informacion_referencia_codigo or None,
                                'Razon':s.ref,
                                }
                            })
                        else:
                            error = True
                            msg = 'El documento de referencia {} no existe! \n'.format(s.fe_doc_ref)
                    else:
                        if s.fe_doc_ref:
                            invoice_data[s.fe_doc_type].update({
                                    'InformacionReferencia':{
                                    'TipoDoc':s.fe_tipo_documento_referencia,
                                    'Numero':s.fe_doc_ref,
                                    'FechaEmision':s.fe_informacion_referencia_fecha.astimezone(tz=pytz.timezone('America/Costa_Rica')).isoformat('T'),
                                    'Codigo':s.fe_informacion_referencia_codigo or None,
                                    'Razon':s.ref,
                                    }
                                })
            else:
                if s.fe_doc_ref:
                    invoice_data[s.fe_doc_type].update({
                        'InformacionReferencia':{
                            'TipoDoc':s.fe_tipo_documento_referencia,
                            'Numero':s.fe_doc_ref,
                            'FechaEmision': s.fe_informacion_referencia_fecha.astimezone(tz=pytz.timezone('America/Costa_Rica')).isoformat('T'),
                            'Codigo':s.fe_informacion_referencia_codigo or None,
                            'Razon':s.ref,
                        }
                    })
                            
            if s.narration:
                invoice_data[s.fe_doc_type].update({
                    'Otros':{
                        'OtroTexto':s.narration,
                        #'OtroContenido':'ELEMENTO OPCIONAL'
                    }
                })
            #PDF de FE,FEE,FEC,ND,NC
            #En caso de que el server-side envie el mail

            invoice_data[s.fe_doc_type].update({'PDF':s._get_pdf_bill(s.id)})
            return invoice_data#s.invoice

    @api.model
    def cron_send_json(self):
        _logger.info(f"DEF1336 =====")
        log.info('--> factelec-Invoice-build_json')
        invoice_list = self.env['account.move'].search(['&',('fe_server_state','=',False),('state','=','posted'),('fe_server_state','!=','Importada Manual'),('type','!=','entry')])
        #log.info('-->invoice_list %s',invoice_list)
        for invoice in invoice_list:
            if invoice.company_id.country_id.code == 'CR' and invoice.fe_in_invoice_type != 'OTRO' and invoice.journal_id.type == 'sale':
                try:
                    log.info('-->consecutivo %s',invoice.name)
                    invoice.confirm_bill()
                except Exception as ex:
                    invoice.write_chatter(ex)
                    invoice.update({
                        'fe_server_state':'error'
                    })

        
    def mostrar_wizard_nota_debito(self):
        _logger.info(f"DEF1353 =====")
        return {
                'type': 'ir.actions.act_window',
                'name': 'Nota Débito',
                'res_model': 'account.move.debit',
                'view_type': 'form',
                'view_mode': 'form',
                'views': [(False, 'form')],
                'target': 'new',
                'context': {
                    'active_id':self.id,
                    'doc_ref':self.name,
                    'journal_id': self.journal_id.id
                 }
             }

    @api.onchange("currency_id","invoice_date",)
    def _onchange_currency_rate(self):
        _logger.info(f"DEF1416 ===== _onchange_currency_rate self: {self} comentado por upgrade")  # comentado por upgrade
        #buscar error con respecto a dolares
        '''for s in self:
            log.info('-->577381353')
            if s.currency_id.name == "USD": 
                date = None
                if not s.invoice_date:
                    date = time.strftime("%Y-%m-%d")
                else:
                    date = s.invoice_date 
                                        
                s._rate(date)'''
    
    
    @api.onchange("journal_id",)
    def _onchange_journal_id(self):
        _logger.info(f"DEF1432 _onchange_journal_id self: {self} Comentado por Upgrade\nContext: {self._context}\n")
        default_move_type = self._context.get('default_move_type')
        _logger.info(f"DEF1434 default_move_type: {default_move_type}\n")
        if default_move_type == "out_refund":
            self.fe_doc_type  = "NotaCreditoElectronica"
        
        '''
        self.fe_in_invoice_type = 'OTRO'
        if self.journal_id:
            if len(self.journal_id.sequence_id.prefix) == 10 :
                if self.journal_id.sequence_id.prefix[8:10] == '08':
                    self.fe_in_invoice_type = 'FEC'
                elif self.journal_id.sequence_id.prefix[8:10] == '09':
                    self.fe_in_invoice_type = 'FEX'
                elif self.journal_id.sequence_id.prefix[8:10] == '01':
                    self.fe_in_invoice_type = 'FE'
                elif self.journal_id.sequence_id.prefix[8:10] == '02':
                    self.fe_in_invoice_type = 'ND'
                else:
                    self.fe_in_invoice_type = 'OTRO'
            else:
                self.fe_in_invoice_type = 'OTRO'
                log.info('largo del prefijo del diario menor a 10')
        '''
    
    @api.model
    def default_fe_in_invoice_type(self):
        _logger.info(f"DEF1454 Upgrade Comentado este procedimiento default_fe_in_invoice_type\n")
        
        '''
        #journal = super(AccountMoveFunctions, self)._get_default_journal()
        journal = self.env['account.journal'].search([('company_id', '=', self.env.company.id), ('type', '=', 'general')], limit=1)
        if len(journal.sequence_id.prefix) == 10 :
                if journal.sequence_id.prefix[8:10] == '08':
                   return 'FEC'
                elif journal.sequence_id.prefix[8:10] == '09':
                    return 'FEX'
                elif journal.sequence_id.prefix[8:10] == '01':
                    return 'FE'
                elif journal.sequence_id.prefix[8:10] == '02':
                    return 'ND'
                else:
                    return 'OTRO'
        else:
            return 'OTRO'
        '''
