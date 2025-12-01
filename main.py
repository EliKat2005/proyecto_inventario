import streamlit as st
import psycopg
import pandas as pd
from datetime import date
import warnings

# --- SUPRESIÓN DE ADVERTENCIAS ---
# Evita que la consola se llene de alertas de Pandas/SQLAlchemy
warnings.filterwarnings('ignore', category=UserWarning, module='pandas')

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Sistema de Inventario Pro", layout="wide", page_icon="📦")

# --- CONEXIÓN SEGURA USANDO SECRETS ---
def get_connection():
    try:
        # Autocommit es necesario para que pandas funcione mejor con transacciones simples
        return psycopg.connect(
            dbname=st.secrets["postgres"]["dbname"],
            user=st.secrets["postgres"]["user"],
            password=st.secrets["postgres"]["password"],
            host=st.secrets["postgres"]["host"],
            port=st.secrets["postgres"]["port"],
            autocommit=True 
        )
    except Exception as e:
        st.error(f"❌ Error conectando a la BD: {e}")
        return None

# --- FUNCIÓN AUXILIAR PARA CARGAR PRODUCTOS EN DROPDOWN ---
def obtener_lista_productos():
    conn = get_connection()
    lista = []
    if conn:
        try:
            # Usamos cursor normal para evitar dependencias de pandas aquí
            with conn.cursor() as cur:
                cur.execute("SELECT codigo_sku, nombre FROM productos ORDER BY nombre")
                rows = cur.fetchall()
                lista = [f"{row[0]} - {row[1]}" for row in rows]
        except Exception as e:
            st.error(f"Error cargando lista: {e}")
        finally:
            conn.close()
    return lista

# --- INTERFAZ PRINCIPAL ---
st.title("🚀 Sistema de Inventario Automatizado")

# Menú lateral
menu = st.sidebar.radio(
    "Acciones Rápidas", 
    ["📊 Dashboard Inteligente", "📝 Registrar (Manual)", "📂 Carga Masiva (CSV)", "⚙️ Gestión Productos"]
)

# ==============================================================================
# 1. DASHBOARD INTELIGENTE
# ==============================================================================
if menu == "📊 Dashboard Inteligente":
    st.header("Visión General del Negocio")
    
    conn = get_connection()
    if conn:
        try:
            # Pandas warning fix: psycopg3 connection is valid but pandas complaints. We ignore the warning.
            df = pd.read_sql("SELECT * FROM fn_obtener_estado_inventario()", conn)
            
            # KPIs Superiores
            kpi1, kpi2, kpi3, kpi4 = st.columns(4)
            kpi1.metric("📦 Total Productos", len(df))
            kpi2.metric("🔢 Stock Total", df['stock_actual'].sum() if not df.empty else 0)
            
            # Filtro de críticos
            if not df.empty:
                criticos = df[df['alerta_estado'] == 'CRÍTICO']
                num_criticos = len(criticos)
                valor_aprox = (df['stock_actual'] * 10).sum()
            else:
                num_criticos = 0
                valor_aprox = 0

            kpi3.metric("🚨 Alerta Crítica", num_criticos, delta_color="inverse")
            kpi4.metric("💰 Valor Estimado (Ref)", f"${valor_aprox:,.2f}")

            st.divider()

            # Gráficos y Tablas
            # Verificamos si Plotly está instalado, si no, mostramos aviso
            try:
                import plotly.express as px
                col_graf, col_tabla = st.columns([1, 2])
                with col_graf:
                    st.subheader("Distribución por Estado")
                    if not df.empty:
                        fig = px.pie(df, names='alerta_estado', title='Salud del Stock', 
                                     color='alerta_estado',
                                     color_discrete_map={'CRÍTICO':'red', 'BAJO':'orange', 'NORMAL':'green'})
                        st.plotly_chart(fig, use_container_width=True)
            except ImportError:
                st.warning("Instala plotly para ver gráficos: 'uv add plotly'")
                col_tabla = st.container()

            with col_tabla:
                st.subheader("Detalle de Existencias")
                
                def color_alerta(val):
                    colors = {'CRÍTICO': '#ffcccc', 'BAJO': '#fff4cc', 'NORMAL': '#ccffcc'}
                    return f'background-color: {colors.get(val, "")}; color: black'

                if not df.empty:
                    st.dataframe(
                        df.style.map(color_alerta, subset=['alerta_estado']),
                        use_container_width=True, # Streamlit actualizó esto, ahora funciona bien con warning suprimido o width="stretch"
                        height=400
                    )
        finally:
            conn.close()

# ==============================================================================
# 2. REGISTRO MANUAL (CORREGIDO ERROR DE TIPOS)
# ==============================================================================
elif menu == "📝 Registrar (Manual)":
    st.header("Nuevo Movimiento")
    st.info("Selecciona el producto de la lista.")

    conn = get_connection()
    lista_prods = obtener_lista_productos()
    
    with st.form("form_movimiento"):
        col1, col2 = st.columns(2)
        
        with col1:
            producto_seleccionado = st.selectbox("Buscar Producto", lista_prods) if lista_prods else st.selectbox("Sin conexión", [])
            tipo = st.selectbox("Tipo", ["ENTRADA", "SALIDA"])
            fecha = st.date_input("Fecha", date.today())
        
        with col2:
            cantidad = st.number_input("Cantidad", min_value=1, value=1)
            valor = st.number_input("Valor Unitario ($)", min_value=0.00, value=0.00, step=0.1)

        btn_guardar = st.form_submit_button("💾 Registrar Transacción", type="primary")

        if btn_guardar and producto_seleccionado:
            sku_real = producto_seleccionado.split(" - ")[0]
            
            try:
                with conn.cursor() as cur:
                    # --- CORRECCIÓN CRÍTICA AQUÍ ---
                    # Usamos ::INT y ::NUMERIC para forzar el tipo de dato en Postgres
                    cur.execute(
                        "CALL sp_registrar_movimiento(%s, %s, %s, %s::INT, %s::NUMERIC)",
                        (sku_real, fecha, tipo, cantidad, valor)
                    )
                    # No hace falta commit manual si autocommit=True en la conexión
                    st.toast(f"✅ Éxito: {tipo} de {sku_real} registrado.", icon="🎉")
            except psycopg.errors.RaiseException as e:
                st.error(f"⛔ {e.diag.message_primary}")
            except Exception as e:
                st.error(f"Error técnico: {e}")
    
    if conn: conn.close()

# ==============================================================================
# 3. CARGA MASIVA
# ==============================================================================
elif menu == "📂 Carga Masiva (CSV)":
    st.header("Importación Masiva de Datos")
    archivo = st.file_uploader("Sube tu archivo (CSV)", type=["csv"])
    
    if archivo:
        try:
            df_upload = pd.read_csv(archivo)
            st.write("Vista previa:", df_upload.head(3))
            
            if st.button("🚀 Procesar Archivo"):
                conn = get_connection()
                barra = st.progress(0)
                exitos = 0
                errores = []

                for i, row in df_upload.iterrows():
                    try:
                        sku = row['Código']
                        tipo_mov = 'ENTRADA' 
                        cant = row['cant'] if pd.notna(row['cant']) else 0
                        val = row['Valor Unitar'] if pd.notna(row['Valor Unitar']) else 0
                        
                        if pd.isna(sku): continue 

                        with conn.cursor() as cur:
                            # Aplicamos la misma corrección de tipos aquí
                            cur.execute(
                                "CALL sp_registrar_movimiento(%s, %s, %s, %s::INT, %s::NUMERIC)",
                                (str(sku), date.today(), tipo_mov, int(cant), float(val))
                            )
                        exitos += 1
                    except Exception as e:
                        errores.append(f"Fila {i}: {e}")
                    barra.progress((i + 1) / len(df_upload))

                conn.close()
                st.success(f"Proceso finalizado. ✅ {exitos} procesados.")
                if errores: st.expander("Ver errores").write(errores)

        except Exception as e:
            st.error(f"Error leyendo el archivo: {e}")

# ==============================================================================
# 4. GESTIÓN PRODUCTOS
# ==============================================================================
elif menu == "⚙️ Gestión Productos":
    st.header("Catálogo Maestro")
    
    with st.form("nuevo_prod"):
        c1, c2 = st.columns(2)
        sku = c1.text_input("SKU").strip()
        cat = c2.text_input("Categoría")
        nom = st.text_input("Nombre Producto")
        min_stock = st.slider("Stock Mínimo para Alerta", 1, 50, 5)
        
        if st.form_submit_button("Guardar Producto"):
            try:
                conn = get_connection()
                with conn.cursor() as cur:
                    cur.execute("CALL sp_gestionar_producto(%s, %s, %s, %s::INT)", 
                                (sku, cat, nom, min_stock))
                conn.close()
                st.success("Producto guardado.")
            except Exception as e:
                st.error(str(e))