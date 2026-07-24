use axum::{
    routing::get,
    Router,
};


#[tokio::main]
async fn main() {
    // single route
    let app = Router::new().route("/", get(|| async {"This is real time Voice AI Assisitance for you to hand holding  like mentor particularly to understand codebased no need to paste code on coding agent"}));

    // run our app with hyper, listening globally on port 3000
    let listner = tokio::net::TcpListener::bind("0.0.0.0:3000").await.unwrap();
    axum::serve(listner, app).await.unwrap();
}
