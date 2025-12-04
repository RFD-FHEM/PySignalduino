// docToolchain configuration file
docToolchain {
    // Defines the directory where the documentation source files are located
    docDir = "docs"
    
    // Configure the build to output to build/site/html for GitHub Pages deployment
    // (This is the expected artifact path in ./github/workflows/docs.yml)
    build.html5.outputDir = 'build/site/html'

    // Configure Asciidoctor to use the :description: and :keywords: attributes 
    // to generate the meta tags for search engine optimization.
    // 'docinfo': 'shared' is key to ensuring document info (like meta tags) is included.
    config.asciidoctorConfig = [
        attributes: [
            'docinfo': 'shared' 
        ]
    ]
}