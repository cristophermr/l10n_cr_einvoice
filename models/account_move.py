from odoo import models, fields, api, exceptions
from datetime import datetime,timezone
import pytz

class AccountMove(models.Model):
    _inherit = "account.move"

    clave_proveedor = fields.Char("Clave Proveedor")
    numero_consecutivo_aceptacion = fields.Char("Numero Consecutivo Aceptacion")
    ''' 
    # 1725475294
    date = fields.Date(string='Date', required=True, index=True, readonly=True,
        states={'draft': [('readonly', False)]},
         default=datetime.now(tz=pytz.timezone('America/Costa_Rica')).strftime("%Y-%m-%d %H:%M:%S"))
    
    invoice_date = fields.Date(string='Invoice/Bill Date', readonly=True, index=True, copy=False,
        states={'draft': [('readonly', False)]},
        default=datetime.now(tz=pytz.timezone('America/Costa_Rica')).strftime("%Y-%m-%d %H:%M:%S"))
    '''
    fe_clave = fields.Char(string="Clave", size=50, copy=False)
    source_date = fields.Datetime(string="Fecha Emision_S")
    fe_fecha_emision = fields.Char(string="Fecha Emision")
    fe_payment_type = fields.Selection([
        ('01', 'Efectivo'),
        ('02', 'Tarjeta'),
        ('03', 'Cheque'),
        ('04', 'Transferencia - depósito bancario'),
        ('05', 'Recaudado por tercero'),
        ('99', ' Otros'),
    ], string="Tipo de pago", track_visibility='onchange',required=False,
    states={'posted': [('readonly', True)]})  #Cambio de True a False, se debe colocar True pero en la vista Invoice

    fe_receipt_status = fields.Selection([
           ('1', 'Normal'),
           ('2', 'Contingencia'),
           ('3', 'Sin Internet'),
    ], string="Situación del comprobante", track_visibility='onchange',required=False, 
    states={'posted': [('readonly', True)]}) #Cambio de True a False, se debe colocar True pero en la vista Invoice
    fe_doc_type = fields.Selection([
            ('FacturaElectronica', 'Factura Electronica'),
            ('NotaDebitoElectronica', 'Nota de Debito Electronica'),
            ('NotaCreditoElectronica', 'Nota de Credito Electronica'),
            ('TiqueteElectronico', 'Tiquete Electronico'),
            ('MensajeReceptor', 'Mensaje Receptor'),
            ('FacturaElectronicaCompra', 'Factura Electronica de Compra'),
            ('FacturaElectronicaExportacion', 'Factura Electronica de Exportacion'),
        ],
        default=lambda self: self.fields_get().get('fe_doc_type').get('selection')[0][0],
        string="Tipo Documento"
    )
    fe_doc_type_id = fields.Char()

    fe_informacion_referencia_codigo = fields.Selection([
        ('01', 'Anula Documento de Referencia'),
        ('02', 'Corrige monto'),
        ('04', 'Referencia a otro documento'),
        ('05', 'Sustituye comprobante provisional por contingencia.'),
        ('99', 'Otros'),
    ], string="Codigo de Referencia", track_visibility='onchange',
    states={'posted': [('readonly', True)]})

    fe_informacion_referencia_fecha = fields.Datetime(string="Fecha Informacion Referencia")

    tax_condition = fields.Selection(
        string="Condicion del IVA",
        selection= [
                ('01', 'General Credito IVA'),
                ('02', 'General Crédito parcial del IVA'),
                ('03', 'Bienes de Capital'),
                ('04', 'Gasto corriente no genera crédito'),
                ('05', 'Proporcionalidad'),
            ],
    )

    fe_name_xml_sign = fields.Char(string="nombre xml firmado",copy=False )
    fe_xml_sign = fields.Binary(string="XML firmado",copy=False )
    fe_name_xml_hacienda = fields.Char(string="nombre xml hacienda",copy=False )
    fe_xml_hacienda = fields.Binary(string="XML Hacienda",copy=False )# 1570034790
    fe_server_state = fields.Char(string="Estado Hacienda",copy=False )

    #FIELDS FOR SUPPLIER INVOICE
    fe_xml_supplier = fields.Binary(string="Factura XML", states={'posted': [('readonly', True)]}) # 1569524296
    fe_xml_supplier_name = fields.Char(string="Nombre XML", )
    fe_xml_supplier_xslt = fields.Html(string="Representacion Grafica", )

    fe_xml_supplier_hacienda = fields.Binary(string="Factura XML", )# 1569524732
    fe_xml_supplier_hacienda_name = fields.Char(string="Nombre XML", )

    fe_msg_type = fields.Selection([ # 1570035130
            ('1', 'Accept'),
            ('2', 'Partially Accept'),
            ('3', 'Reject'),
        ], string="Mensaje", track_visibility="onchange",
    states={'posted': [('readonly', True)]})

    fe_detail_msg = fields.Text(string="Detalle Mensaje", size=80, copy=False,
    states={'posted': [('readonly', True)]})# 1570035143

    fe_total_servicio_gravados = fields.Float(string="Total servicios gravados",digits=(15,2), compute = '_compute_total_serv_merc' )
    fe_total_servicio_exentos = fields.Float(string="Total servicios exentos",digits=(15,2), compute = '_compute_gravados_exentos' )

    TotalServExonerado = fields.Float(string='Servicio Exonerados',compute="_compute_exoneraciones", digits=(15, 2))

    fe_total_mercancias_gravadas = fields.Float(string="Total mercancias gravadas",digits=(15,2), compute = '_compute_gravados_exentos' )
    fe_total_mercancias_exentas = fields.Integer(string="Total mercancias exentas",digits=(15,2), compute = '_compute_gravados_exentos')
    TotalMercExonerada = fields.Float(string='Mercancias Exonerados',compute="_compute_exoneraciones", digits=(15, 2))
    
    fe_total_gravado = fields.Float(string="Total gravado",digits=(15,2), compute = '_compute_gravados_exentos')
    fe_total_exento = fields.Float(string="Total exento",digits=(15,2), compute = '_compute_gravados_exentos' )
    TotalExonerado = fields.Float(string='Total Exonerado',compute="_compute_exoneraciones", digits=(15,2))
    
    fe_total_venta = fields.Float(string="Total venta",compute = '_compute_total_venta' )
    fe_total_descuento = fields.Float(string="Total descuento", compute = '_compute_total_descuento' )

    fe_activity_code_id = fields.Many2one(
        string="Actividad económica",
        comodel_name="activity.code",
        ondelete="set null",
        states={'posted': [('readonly', True)]}
    )
    
    fe_in_invoice_type = fields.Selection(#1569867120
        string="Tipo Documento",
        selection=[
                ('ME', 'Mensaje Aceptación'),
                ('FE', 'Factura Electronica'),
                ('FEC', 'Factura Electronica Compra'),
                ('FEX', 'Factura Electronica Exportación'),
                ('ND', 'Nota Débito'),   
                ('OTRO', 'Otros'),                
        ],
       #default=lambda self: self.default_fe_in_invoice_type(),   ''' Comentado por Upgrade xxxxxxxx
    )
    
    fe_current_country_company_code = fields.Char(string="Codigo pais de la compañia actual",compute="_get_country_code")
    
    fe_tipo_documento_referencia = fields.Selection(
        string="Tipo documento de referencia",
        selection=[                
                ('01','Factura electrónica'),
                ('02','Nota de débito electrónica'),
                ('03','Nota de crédito electrónica'),
	        ('04','Tiquete electrónico'),
                ('05','Nota de despacho'),
	        ('06','Contrato'),
                ('07','Procedimiento'),
                ('08','Comprobante emitido en contingencia'),
                ('09','Devolución mercadería'),
                ('10','Sustituye factura rechazada por el Ministerio de Hacienda'),
	        ('11','Sustituye factura rechazada por el Receptor del comprobante'),
                ('12','Sustituye Factura de exportación'),
                ('13','Facturación mes vencido'),
		('14','Comprobante aportado por contribuyente del Régimen de Tributación Simplificado'),
		('15','Sustituye una Factura electrónica de Compra'),
                ('99','Otros'),
        ],
        states={'posted': [('readonly', True)]}
    )
    
    fe_condicion_impuesto = fields.Selection(
        string="Condición de impuestos",
        selection=[
                ('01', 'Genera crédito IVA'),
                ('02', 'Genera Crédito parcial del IVA'),
                ('03', 'Bienes de Capital'),
                ('04', 'Gasto corriente no genera crédito'),
                ('05', 'Proporcionalidad'),
        ],
    )
    
    fe_currency_rate = fields.Char(compute="_compute_currency_rate", string="Tipo de cambio")
    
    fe_doc_ref = fields.Char(string="Documento Electrónico de Referencia",states={'posted': [('readonly', True)]})
    
    electronic_doc_id = fields.Many2one('electronic.doc', string='XML',readonly = True, )
    
    debit_note = fields.Boolean(string='Nota Debito?', invisible = True, default = False )

    fecha_factura_simplificada = fields.Datetime(string='Fecha Emisión')


