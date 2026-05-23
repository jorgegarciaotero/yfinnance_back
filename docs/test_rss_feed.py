import sys
import feedparser

def test_rss(feed_url: str, source_name: str):
    print(f"\n📡 Conectando al feed de {source_name}: {feed_url}")
    
    # Parsear el RSS
    feed = feedparser.parse(feed_url)
    
    if feed.bozo:
        print("❌ Error al parsear el feed o URL no válida.")
        return
        
    print(f"✅ Feed obtenido correctamente. Título: {feed.feed.get('title', 'Sin título')}")
    print(f"Total de noticias en el feed: {len(feed.entries)}")
    print("-" * 50)
    
    # Mostrar los 3 últimos artículos
    for i, entry in enumerate(feed.entries[:3]):
        print(f"\n📰 NOTICIA {i+1}:")
        print(f"Título:       {entry.get('title')}")
        print(f"Publicado:    {entry.get('published')}")
        print(f"Enlace:       {entry.get('link')}")
        
        # El resumen a veces viene con HTML, extraemos una parte
        summary = entry.get('summary', 'Sin resumen')
        print(f"Resumen:      {summary[:150]}...")

if __name__ == "__main__":
    # Nota: Antes de ejecutar, asegúrate de instalar la librería:
    # pip install feedparser
    
    feeds_de_prueba = [
        ("https://search.cnbc.com/rs/search/combinedcms/view.xml?profile=12000000&id=10000664", "CNBC Economy"),
        ("https://finance.yahoo.com/news/rssindex", "Yahoo Finance Top News")
    ]
    
    for url, nombre in feeds_de_prueba:
        test_rss(url, nombre)